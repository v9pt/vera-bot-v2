"""Thin FastAPI layer over the vera package."""
from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor, TimeoutError as FutureTimeout

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from vera.compose import compose
from vera.facts import resolve
from vera.polish import polish_all, polish_enabled
from vera.reply import handle_reply
from vera.select import MAX_ACTIONS, choose, sent_key
from vera.store import store

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
log = logging.getLogger("vera.app")

MAX_CONTEXT_BYTES = 500 * 1024
TICK_BUDGET_S = 20.0
REPLY_BUDGET_S = 4.5
START_TIME = time.time()

app = FastAPI(title="Vera bot", version="2.0")
_pool = ThreadPoolExecutor(max_workers=4)


@app.api_route("/", methods=["GET", "HEAD"])
def home():
    return {"service": "Vera bot", "status": "running", "version": "2.0", "health": "/v1/healthz", "metadata": "/v1/metadata"}


@app.api_route("/v1/healthz", methods=["GET", "HEAD"])  # uptime monitors send HEAD
def healthz():
    return {"status": "ok", "uptime_seconds": int(time.time() - START_TIME), "contexts_loaded": store.counts()}


@app.get("/v1/metadata")
def metadata():
    return {
        "team_name": "Huzaifa Mulla",
        "team_members": ["Huzaifa Mulla"],
        "model": "rule-based composer + optional Gemini/Groq polish",
        "approach": ("Deterministic per-trigger-kind composers over a grounded fact-sheet (every number, date and name "
                     "comes from pushed context), one signal and one CTA per message, optional LLM polish that is "
                     "rejected unless it passes the same grounding validator, and a rule-based reply state machine."),
        "contact_email": "huzaifa.mulla.ug22@nsut.ac.in",
        "version": "2.0",
    }


@app.post("/v1/context")
async def context(request: Request):
    raw = await request.body()
    if len(raw) > MAX_CONTEXT_BYTES:
        return JSONResponse(status_code=413, content={"accepted": False, "reason": "payload_too_large"})
    try:
        body = json.loads(raw or b"{}")
    except ValueError:
        return JSONResponse(status_code=400, content={"accepted": False, "reason": "invalid_json"})
    if not isinstance(body, dict):
        return JSONResponse(status_code=400, content={"accepted": False, "reason": "invalid_json"})
    result = store.put(body.get("scope"), body.get("context_id"), body.get("version", 1), body.get("payload") or {})
    if not result["accepted"] and result["reason"] == "invalid_scope":
        return JSONResponse(status_code=400, content=result)
    if not result["accepted"]:
        return JSONResponse(status_code=409, content=result)
    log.info("context %s/%s v%s accepted", body.get("scope"), body.get("context_id"), body.get("version", 1))
    return result


def _checkin_trigger(merchant_id: str) -> dict:
    return {"id": f"checkin_{merchant_id}", "scope": "merchant", "kind": "curious_ask_due", "merchant_id": merchant_id,
            "customer_id": None, "payload": {}, "urgency": 1, "suppression_key": f"checkin:{merchant_id}"}


def _collect(payload: dict) -> tuple[list[dict], str | None]:
    """Returns (triggers, now_for_expiry). Triggers the caller names explicitly are never expired."""
    now = payload.get("now") if isinstance(payload.get("now"), str) else None
    ids = payload.get("available_triggers")
    merchant_id = payload.get("merchant_id")
    if isinstance(ids, list) and ids:
        out = []
        for tid in ids:
            t = store.get("trigger", str(tid))
            if t:
                t.setdefault("id", str(tid))
                out.append(t)
            elif store.get("merchant", str(tid)):
                out.append(_checkin_trigger(str(tid)))
        return out, None
    triggers = []
    for tid, t in store.all("trigger").items():
        t.setdefault("id", tid)
        if not merchant_id or t.get("merchant_id") == merchant_id:
            triggers.append(t)
    if merchant_id and not triggers and store.get("merchant", merchant_id):
        return [_checkin_trigger(merchant_id)], None
    return triggers, now


def _versions_key(t: dict) -> str:
    return ".".join(str(store.version_of(s, i)) for s, i in (
        ("trigger", t.get("id")), ("merchant", t.get("merchant_id")), ("customer", t.get("customer_id"))))


def _run_tick(payload: dict, started: float) -> dict:
    triggers, now = _collect(payload)
    chosen = choose(triggers, store.sent_keys, now)
    merchant_id = payload.get("merchant_id")
    if not chosen and merchant_id and not payload.get("available_triggers") and store.get("merchant", merchant_id):
        # Expiry (not suppression) emptied this merchant's triggers: fall back to a check-in.
        unsuppressed = [t for t in triggers if sent_key(t) not in store.sent_keys]
        if unsuppressed:
            chosen = choose([_checkin_trigger(merchant_id)], store.sent_keys, None)
    actions, ctxs = [], {}
    for t in chosen:
        if time.time() - started > TICK_BUDGET_S * 0.5:
            break
        ctx = resolve(store, t)
        if ctx is None:
            log.info("tick skip %s: merchant or category missing", t.get("id"))
            continue
        try:
            action = compose(ctx)
        except Exception:  # noqa: BLE001 - one bad trigger must not sink the tick
            log.exception("compose failed for %s", t.get("id"))
            continue
        action["_cache_key"] = f"{action['trigger_id']}:{_versions_key(t)}"
        actions.append(action)
        ctxs[action["trigger_id"]] = ctx
        if len(actions) >= MAX_ACTIONS:
            break
    if actions and polish_enabled():
        remaining = TICK_BUDGET_S - (time.time() - started) - 1.0
        actions = polish_all(actions, ctxs, max(0.5, remaining))
    for a in actions:
        a.pop("_cache_key", None)
        store.sent_keys.add(sent_key(a))
        store.conversations.setdefault(a["conversation_id"], []).append({"from": "bot", "action": "send", "text": a["body"]})
    log.info("tick: %d candidates, %d actions", len(chosen), len(actions))
    return {"actions": actions}


@app.post("/v1/tick")
async def tick(request: Request):
    started = time.time()
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    return await run_in_threadpool(_run_tick, payload, started)


@app.post("/v1/reply")
async def reply(request: Request):
    try:
        payload = await request.json()
    except ValueError:
        payload = {}
    if not isinstance(payload, dict):
        payload = {}
    fut = _pool.submit(handle_reply, store, payload)
    try:
        return fut.result(timeout=REPLY_BUDGET_S)
    except FutureTimeout:
        return {"action": "wait", "wait_seconds": 1800, "rationale": "Reply handling exceeded budget."}
    except Exception:  # noqa: BLE001
        log.exception("reply failed")
        return {"action": "wait", "wait_seconds": 1800, "rationale": "Could not process reply; waiting."}


@app.post("/v1/teardown")
def teardown():
    store.clear()
    return {"success": True}
