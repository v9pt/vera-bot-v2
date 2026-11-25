"""In-memory versioned context store. All bot state lives here."""
from __future__ import annotations

import copy
import threading
from datetime import datetime, timezone

SCOPES = ("category", "merchant", "customer", "trigger")


class Store:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self.contexts: dict[str, dict[str, dict]] = {s: {} for s in SCOPES}
        self.versions: dict[tuple[str, str], int] = {}
        self.conversations: dict[str, list[dict]] = {}
        self.sent_keys: set[str] = set()
        # Auto-reply counts per merchant: judges may rotate conversation ids.
        self.merchant_auto_replies: dict[str, int] = {}

    def put(self, scope: str, context_id: str, version: int, payload: dict) -> dict:
        if scope not in self.contexts:
            return {"accepted": False, "reason": "invalid_scope"}
        try:
            version = int(version)
        except (TypeError, ValueError):
            version = 1
        key = (scope, str(context_id))
        with self._lock:
            current = self.versions.get(key)
            if current is not None and version < current:
                return {"accepted": False, "reason": "stale_version", "current_version": current}
            self.contexts[scope][str(context_id)] = copy.deepcopy(payload if isinstance(payload, dict) else {})
            self.versions[key] = version
        return {
            "accepted": True,
            "ack_id": f"ack_{scope}_{context_id}_v{version}",
            "stored_at": datetime.now(timezone.utc).isoformat(),
        }

    def get(self, scope: str, context_id: str | None) -> dict | None:
        if context_id is None:
            return None
        with self._lock:
            item = self.contexts.get(scope, {}).get(str(context_id))
            return copy.deepcopy(item) if item is not None else None

    def all(self, scope: str) -> dict[str, dict]:
        with self._lock:
            return copy.deepcopy(self.contexts.get(scope, {}))

    def counts(self) -> dict[str, int]:
        with self._lock:
            return {s: len(v) for s, v in self.contexts.items()}

    def version_of(self, scope: str, context_id: str | None) -> int:
        return self.versions.get((scope, str(context_id)), 0)

    def clear(self) -> None:
        with self._lock:
            for v in self.contexts.values():
                v.clear()
            self.versions.clear()
            self.conversations.clear()
            self.sent_keys.clear()
            self.merchant_auto_replies.clear()


store = Store()
