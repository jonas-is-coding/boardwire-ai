"""Paced, permanent, idempotent follow drip.

* **Paced**: a random ``pace_seconds`` sleep before every follow after the
  first, so a run looks like a person scrolling, not a script.
* **Permanent**: there is no unfollow path in this package, ever.
* **Idempotent**: a candidate is skipped when the authenticated
  ``viewer.following`` state (hydrated in ``discover``) or the ledger says we
  already follow it.

The ledger is written after each follow and **before** the next pacing sleep —
never only at the end of the loop — so a cancelled workflow run keeps every
follow it already made.
"""

from __future__ import annotations

import random
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime
from logging import Logger
from typing import Callable

from src.growth.client import GrowthClient, GrowthClientError, utc_now_iso
from src.growth.discover import Candidate
from src.growth.ledger import GrowthLedger
from src.growth.settings import GrowthConfig

_MAX_CONSECUTIVE_FAILURES = 3


@dataclass(slots=True)
class FollowRunSummary:
    mode: str
    dry_run: bool
    limit: int
    planned: int = 0            # dry-run: follows that would have happened
    followed: int = 0
    skipped_already: int = 0
    failed: int = 0
    aborted: str | None = None
    handles: list[str] = field(default_factory=list)
    started_at: str = ""
    finished_at: str = ""

    @property
    def actions(self) -> int:
        return self.followed + self.planned


def run_follow_drip(
    client: GrowthClient,
    candidates: list[Candidate],
    ledger: GrowthLedger,
    config: GrowthConfig,
    *,
    mode: str,
    logger: Logger,
    limit: int | None = None,
    dry_run: bool = False,
    sleeper: Callable[[float], None] = time.sleep,
    rng: random.Random | None = None,
    now: datetime | None = None,
) -> FollowRunSummary:
    rng = rng or random.Random()
    limit = max(1, limit if limit is not None else config.follows_per_run)
    summary = FollowRunSummary(mode=mode, dry_run=dry_run, limit=limit, started_at=utc_now_iso(now))
    consecutive_failures = 0

    for cand in candidates:
        if summary.actions >= limit:
            break
        if cand.viewer_following or ledger.is_followed(cand.did):
            summary.skipped_already += 1
            continue

        if dry_run:
            logger.info("[dry-run] would follow @%s  score=%.2f  %s", cand.handle, cand.score, cand.why())
            summary.planned += 1
            summary.handles.append(cand.handle)
            continue

        if summary.followed > 0:
            pause = rng.uniform(config.pace_seconds_min, config.pace_seconds_max)
            sleeper(pause)

        try:
            response = client.follow(cand.did, now=now)
        except GrowthClientError as exc:
            summary.failed += 1
            consecutive_failures += 1
            logger.error("Follow failed for @%s: %s", cand.handle, exc)
            if exc.rate_limited:
                summary.aborted = "rate limited"
                break
            if consecutive_failures >= _MAX_CONSECUTIVE_FAILURES:
                summary.aborted = f"{consecutive_failures} consecutive failures"
                break
            continue

        consecutive_failures = 0
        ledger.record_follow(
            did=cand.did,
            handle=cand.handle,
            uri=str(response.get("uri") or ""),
            channel=cand.top_channel,
            score=cand.score,
            mode=mode,
            via=cand.via[:5],
            followed_at=utc_now_iso(now),
        )
        ledger.save()  # persist before the next pacing sleep: an interrupted run keeps its state
        summary.followed += 1
        summary.handles.append(cand.handle)
        logger.info("Followed @%s  score=%.2f  %s", cand.handle, cand.score, cand.why())

    summary.finished_at = utc_now_iso(now)
    if not dry_run:
        ledger.append_run(asdict(summary))
        ledger.save()
    return summary
