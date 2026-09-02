"""Growth ledger: ``data/growth_ledger.json``.

One record per follow the drip ever created, plus the pinned-thread state and
a short run history. The follow drip writes the ledger after *every single
follow, before the pacing sleep*, and the workflow commits it after the run —
so a run that is cancelled mid-drip never loses what it already did.

The ledger is a cache, not the source of truth: the authenticated
``viewer.following`` state from ``getProfiles`` is authoritative and is
checked again on every run.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from src.storage.json_store import JsonStore

LEDGER_VERSION = 1
_MAX_RUN_HISTORY = 90


class GrowthLedger:
    def __init__(self, path: Path, data: dict | None = None) -> None:
        self.path = path
        self.data: dict[str, Any] = {
            "version": LEDGER_VERSION,
            "follows": {},
            "runs": [],
            "pinned_thread": None,
            "profile": None,
        }
        if isinstance(data, dict):
            for key, value in data.items():
                self.data[key] = value
        if not isinstance(self.data.get("follows"), dict):
            self.data["follows"] = {}
        if not isinstance(self.data.get("runs"), list):
            self.data["runs"] = []

    @classmethod
    def load(cls, path: Path) -> "GrowthLedger":
        raw = JsonStore.load(path, default={})
        return cls(path, raw if isinstance(raw, dict) else {})

    def save(self) -> None:
        JsonStore.save(self.path, self.data)

    # -- follows -----------------------------------------------------------

    @property
    def follows(self) -> dict[str, dict]:
        return self.data["follows"]

    def followed_dids(self) -> set[str]:
        return set(self.follows.keys())

    def is_followed(self, did: str) -> bool:
        return did in self.follows

    def record_follow(
        self,
        *,
        did: str,
        handle: str,
        uri: str,
        channel: str,
        score: float,
        mode: str,
        via: list[str],
        followed_at: str,
    ) -> None:
        self.follows[did] = {
            "handle": handle,
            "uri": uri,
            "channel": channel,
            "score": round(float(score), 3),
            "mode": mode,
            "via": list(via),
            "followed_at": followed_at,
        }

    # -- runs --------------------------------------------------------------

    def append_run(self, summary: dict) -> None:
        runs = self.data["runs"]
        runs.append(summary)
        if len(runs) > _MAX_RUN_HISTORY:
            del runs[: len(runs) - _MAX_RUN_HISTORY]

    # -- profile / pinned thread ------------------------------------------

    @property
    def pinned_thread(self) -> dict | None:
        value = self.data.get("pinned_thread")
        return value if isinstance(value, dict) else None

    @pinned_thread.setter
    def pinned_thread(self, value: dict | None) -> None:
        self.data["pinned_thread"] = value

    @property
    def profile(self) -> dict | None:
        value = self.data.get("profile")
        return value if isinstance(value, dict) else None

    @profile.setter
    def profile(self, value: dict | None) -> None:
        self.data["profile"] = value
