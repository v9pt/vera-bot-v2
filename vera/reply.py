"""Rule-based reply classifier and conversation state machine. No LLM, no I/O."""
from __future__ import annotations

import re

from .compose_merchant import L, commas
from .facts import Ctx, build_facts, clean_person_name, human
from .voice import customer_wants_hinglish, salutation, wants_hinglish

AUTO_REPLY = [
    "thank you for contacting", "thanks for contacting", "will respond shortly", "respond shortly",
    "will get back to you", "get back to you shortly", "automated", "auto-reply", "auto reply", "autoreply",
    "out of office", "currently unavailable", "busy right now", "not available right now", "our team will",
    "this is an automated", "aapki jaankari ke liye", "bahut-bahut shukriya", "jald hi sampark", "hum jald",
]
HOSTILE = [
    r"\bstop\b", r"\bspam\b", r"unsubscribe", r"don'?t (message|text|contact)", r"do not (message|text|contact)",
    r"not interested", r"leave me alone", r"band karo", r"mat bhejo", r"bakwas", r"pareshan", r"\bblock\b",
    r"useless", r"\bfraud\b", r"\bscam\b", r"no thanks", r"\bnahi chahiye\b", r"bas karo", r"bother",
]
COMMIT = [
    r"let'?s do it", r"lets do it", r"go ahead", r"\byes\b", r"\byep\b", r"\bhaan\b", r"\bha\b", r"\bok(ay)?\b",
    r"\bsure\b", r"\bdo it\b", r"send it", r"\bproceed\b", r"kar do", r"theek hai", r"thik hai", r"\bchalo\b",
    r"\bconfirm", r"book it", r"sounds good", r"\bdone\b", r"^\s*1\s*$", r"please send", r"send (me )?the",
]
OBJECTION = [
    r"expensive", r"costly", r"mehenga", r"mahenga", r"no budget", r"not now", r"\blater\b", r"baad mein",
    r"time nahi", r"\bbusy\b", r"don'?t have time", r"no time", r"not sure", r"doesn'?t work", r"didn'?t work",
    r"already (have|tried|doing)", r"too much", r"abhi nahi",
]
OPTION_2 = re.compile(r"^\s*(2|option 2|2\.)\s*$")
SKIPPISH = re.compile(r"skip|later|pause|watch|already|baad|rehne|abhi nahi|not now", re.I)
QUESTION_START = re.compile(r"^\s*(what|how|why|when|where|which|who|can|is|are|does|do|kya|kaise|kitna|kab|kyun|kaun)\b", re.I)

AUTO_WAIT_SECONDS = 1800
DEFAULT_WAIT_SECONDS = 1800


def _any(patterns, text) -> bool:
    return any(re.search(p, text) for p in patterns)


def classify(message: str) -> str:
    t = (message or "").strip().lower()
    if not t:
        return "other"
    if any(p in t for p in AUTO_REPLY):
        return "auto_reply"
    if OPTION_2.match(t):
        return "option_2"
    if _any(HOSTILE, t):
        return "hostile"
    if _any(COMMIT, t):
        return "commit"
    if _any(OBJECTION, t):
        return "objection"
    if "?" in t or QUESTION_START.search(t):
        return "question"
    return "other"


DELIVERABLES = {
    "research_digest": "patient recall message", "regulation_change": "audit checklist", "perf_dip": "refreshed offer and post",
    "renewal_due": "renewal link", "festival_upcoming": "festive offer post", "curious_ask_due": "Google post",
    "winback_eligible": "win-back message", "ipl_match_today": "match-night post", "review_theme_emerged": "review reply template",
    "milestone_reached": "review-request message", "active_planning_intent": "full package draft", "seasonal_perf_dip": "member-referral post",
    "supply_alert": "customer WhatsApp note", "category_seasonal": "shelf plan and post", "gbp_unverified": "verification steps",
    "cde_opportunity": "registration link", "competitor_opened": "post built on your strength", "perf_spike": "follow-up post",
    "dormant_with_vera": "status update",
}


def _merchant_ctx(store, merchant_id: str | None, trigger: dict | None) -> tuple[dict, dict, dict]:
    merchant = store.get("merchant", merchant_id) if merchant_id else None
    category = store.get("category", (merchant or {}).get("category_slug")) if merchant else None
    facts = build_facts(category or {}, merchant or {}, trigger or {}, None, None) if merchant else {}
    return merchant or {}, category or {}, facts


def _trigger_for(store, conversation_id: str) -> dict | None:
    if conversation_id.startswith("conv_"):
        return store.get("trigger", conversation_id[len("conv_"):])
    return None


def _send(body: str, rationale: str, cta: str = "open_ended") -> dict:
    return {"action": "send", "body": body, "cta": cta, "rationale": rationale}


def _wait(seconds: int, rationale: str) -> dict:
    return {"action": "wait", "wait_seconds": seconds, "rationale": rationale}


def _end(rationale: str) -> dict:
    return {"action": "end", "rationale": rationale}


QUESTION_FACTS = [
    (r"\bviews?\b", "views_30d", "Your profile had {v} views in the last 30 days.", "Pichhle 30 din mein profile pe {v} views aaye."),
    (r"\bcalls?\b", "calls_30d", "You got {v} calls from the profile in the last 30 days.", "Pichhle 30 din mein profile se {v} calls aaye."),
    (r"\bctr\b|click", "ctr", "Your profile CTR is {v}.", "Aapka profile CTR {v} hai."),
    (r"renew|price|cost|kitna|charge|fee|plan", "plan", "You're on the {v} plan.", "Aap {v} plan pe hain."),
    (r"offer|discount|deal", "active_offer", "Your live offer is \"{v}\".", "Aapka live offer \"{v}\" hai."),
]


def handle_reply(store, payload: dict) -> dict:
    conv_id = str(payload.get("conversation_id") or "conv_unknown")
    merchant_id = payload.get("merchant_id")
    message = str(payload.get("message") or "")
    convo = store.conversations.setdefault(conv_id, [])
    convo.append({"from": payload.get("from_role") or "merchant", "text": message,
                  "turn": payload.get("turn_number", payload.get("turn"))})

    if any(e.get("state") == "ended" for e in convo):
        return _end("Conversation already closed.")

    cls = classify(message)
    trigger = _trigger_for(store, conv_id)
    merchant, category, facts = _merchant_ctx(store, merchant_id, trigger)
    h = wants_hinglish(merchant) if merchant else False
    name = salutation(Ctx(category, merchant, trigger or {}, None, None)) if merchant else ""
    hi = f"{name}, " if name else ""

    def finish(result: dict) -> dict:
        convo.append({"from": "bot", "action": result["action"], "class": cls, "text": result.get("body", ""),
                      **({"state": "ended"} if result["action"] == "end" else {})})
        return result

    if cls == "auto_reply":
        conv_n = sum(1 for e in convo if e.get("from") != "bot" and classify(e.get("text", "")) == "auto_reply")
        key = str(merchant_id or conv_id)
        store.merchant_auto_replies[key] = store.merchant_auto_replies.get(key, 0) + 1
        n = max(conv_n, store.merchant_auto_replies[key])
        texts = [e.get("text") for e in convo if e.get("from") != "bot"]
        if n >= 3 or texts.count(message) >= 3:
            return finish(_end("Repeated auto-replies; nobody is reading. Closing to avoid spamming."))
        if n == 2:
            return finish(_wait(AUTO_WAIT_SECONDS, "Second auto-reply; backing off before trying again."))
        return finish(_send(L(h, f"{hi}looks like an auto-reply. When the owner has a moment, reply 1 and I'll pick this up.",
                              f"{hi}yeh auto-reply lag raha hai. Owner free hon toh 1 reply kar dein, main wahin se continue karungi."),
                            "Auto-reply detected once; one short nudge for the owner.", "binary"))

    if cls == "hostile":
        return finish(_end("Asked to stop; closing this conversation."))

    is_customer = bool((trigger or {}).get("scope") == "customer" or payload.get("from_role") == "customer"
                       or payload.get("customer_id"))
    if is_customer:
        return finish(_customer_reply(store, cls, trigger, payload, facts))

    if cls == "option_2":
        last = next((e.get("text", "") for e in reversed(convo) if e.get("from") == "bot" and e.get("text")), "")
        m = re.search(r"(?:or 2 to|ya 2 —)\s*(.+?)\.\s*$", last)
        if not m:
            return finish(_wait(DEFAULT_WAIT_SECONDS, "Picked option 2 with no known options; waiting."))
        option = m.group(1).strip()
        if re.search(r"pause", option, re.I):
            return finish(_end("Merchant chose to pause messages."))
        if SKIPPISH.search(option):
            return finish(_wait(DEFAULT_WAIT_SECONDS * 48, f"Merchant chose '{option}'; backing off."))
        return finish(_send(L(h, f"Got it{', ' + name if name else ''} — {option}. I'll set that up and share it here next.",
                              f"Theek hai{', ' + name if name else ''} — {option}. Main set karke yahin share karti hoon."),
                            f"Merchant chose option 2 ('{option}'); acting on it.", "none"))

    if cls == "commit":
        thing = DELIVERABLES.get((trigger or {}).get("kind", ""))
        en_what = f"drafting the {thing} now" if thing else "drafting it now"
        hi_what = f"{thing} abhi draft kar rahi hoon" if thing else "abhi draft kar rahi hoon"
        return finish(_send(L(h, f"Done — {hi}{en_what}. Next: I'll share it here for your approval; nothing goes live without your OK.",
                              f"Done — {hi}{hi_what}. Next: yahin share karungi approval ke liye; aapke OK ke bina kuch live nahi hoga."),
                            "Merchant committed; switching to action mode with the concrete next step.", "none"))

    if cls == "objection":
        if any(e.get("from") == "bot" and e.get("class") == "objection" and e.get("action") == "send" for e in convo):
            return finish(_wait(DEFAULT_WAIT_SECONDS * 2, "Objection repeated; giving space rather than pushing."))
        anchor = ""
        if facts.get("views_30d"):
            anchor = L(h, f" {commas(facts['views_30d'])} people viewed your profile last month — a small fix converts more of them.",
                       f" Pichhle mahine {commas(facts['views_30d'])} logon ne aapka profile dekha — chhota sa fix unme se zyada ko customer banata hai.")
        elif facts.get("active_offer"):
            anchor = L(h, f" It builds on your existing \"{facts['active_offer']}\", so no new spend.",
                       f" Yeh aapke existing \"{facts['active_offer']}\" pe hi build hota hai, koi naya kharcha nahi.")
        return finish(_send(L(h, f"Fair point, {name or 'no problem'}.{anchor} I do the drafting; you just approve. Reply 1 if you want it, or 2 to drop it.",
                              f"Bilkul samajh sakti hoon{', ' + name if name else ''}.{anchor} Drafting main karungi, aapko bas approve karna hai. Reply 1 — chahiye, ya 2 — rehne dein."),
                            "One reframe using a merchant fact; will wait if the objection repeats.", "binary"))

    if cls == "question":
        low = message.lower()
        for pat, key, en, hin in QUESTION_FACTS:
            if re.search(pat, low) and facts.get(key):
                v = commas(facts[key]) if key.endswith("_30d") else facts[key]
                return finish(_send(L(h, f"{hi}{en.format(v=v)} Reply 1 and I'll put it to work this week, or 2 to leave it.",
                                      f"{hi}{hin.format(v=v)} Reply 1 — is hafte kaam pe lagate hain, ya 2 — rehne dein."),
                                    f"Answered from merchant fact '{key}' and steered back with one CTA.", "binary"))
        topic = human((trigger or {}).get("kind") or "") or L(h, "your listing", "aapki listing")
        return finish(_send(L(h, f"{hi}I'll stay focused on {topic} for your business. Reply 1 to get the draft, or 2 to skip.",
                              f"{hi}main aapke business ke {topic} pe focus rakhungi. Reply 1 — draft bhejun, ya 2 — skip."),
                            "Off-topic or unanswerable question; steering back with one CTA.", "binary"))

    return finish(_wait(DEFAULT_WAIT_SECONDS, "No clear intent; waiting for the merchant."))


def _customer_reply(store, cls: str, trigger: dict | None, payload: dict, facts: dict) -> dict:
    """Replies on customer conversations: never use the merchant salutation or merchant metrics."""
    customer = store.get("customer", (trigger or {}).get("customer_id") or payload.get("customer_id")) or {}
    h = customer_wants_hinglish(customer)
    raw = (customer.get("identity") or {}).get("name")
    name, parent = clean_person_name(raw)
    who = parent or name
    hi = f", {who}" if who else ""
    slots = []
    for key in ("available_slots", "next_session_options", "slots"):
        for s in ((trigger or {}).get("payload") or {}).get(key) or []:
            if isinstance(s, dict) and s.get("label"):
                slots.append(str(s["label"]))
    if cls in ("commit", "option_2"):
        idx = 1 if cls == "option_2" else 0
        if len(slots) > idx:
            return _send(L(h, f"Done{hi} — {slots[idx]} is booked for you. See you then!",
                           f"Done{hi} — {slots[idx]} book ho gaya. Milte hain!"),
                         f"Customer picked option {idx + 1}; confirming that slot.", "none")
        if cls == "option_2":
            return _send(L(h, f"No problem{hi}. Reply with a day and time that suits you and we'll hold it.",
                           f"Koi baat nahi{hi}. Jo din aur time suit kare, reply kar dijiye — hum hold kar lenge."),
                         "Customer declined the offered option; asking for a preferred time.", "open_ended")
        return _send(L(h, f"Done{hi} — noted. We'll confirm the details here shortly.",
                       f"Done{hi} — note kar liya. Details yahin confirm karte hain."),
                     "Customer agreed; confirming.", "none")
    if cls == "question":
        return _send(L(h, f"Thanks{hi} — the team will answer that here personally.",
                       f"Shukriya{hi} — team yahin aapko personally jawaab degi."),
                     "Customer question routed to the merchant's team.", "none")
    if cls == "auto_reply":
        return _wait(AUTO_WAIT_SECONDS, "Customer auto-reply; waiting.")
    return _wait(DEFAULT_WAIT_SECONDS, "No clear intent from the customer; waiting.")
