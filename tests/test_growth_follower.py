from __future__ import annotations

import json
import logging
import random
from pathlib import Path

from src.growth.client import GrowthClientError
from src.growth.discover import Candidate
from src.growth.follower import run_follow_drip
from src.growth.ledger import GrowthLedger
from src.growth.settings import GrowthConfig

_LOGGER = logging.getLogger("test")
_GROWTH_DIR = Path(__file__).resolve().parent.parent / "src" / "growth"


def _cand(did: str, handle: str, *, following: bool = False, score: float = 1.0) -> Candidate:
    return Candidate(did=did, handle=handle, score=score, channels={"seed_follows": score}, via=["@seed.test follows"], viewer_following=following)


class FakeClient:
    def __init__(self, fail: dict[str, Exception] | None = None) -> None:
        self.followed: list[str] = []
        self.fail = fail or {}

    def follow(self, did: str, now=None) -> dict:
        if did in self.fail:
            raise self.fail[did]
        self.followed.append(did)
        return {"uri": f"at://did:plc:me/app.bsky.graph.follow/{len(self.followed)}", "cid": "cid"}


def _config(tmp_path: Path, **overrides) -> GrowthConfig:
    base = dict(follows_per_run=3, pace_seconds_min=1.0, pace_seconds_max=2.0, ledger_path=tmp_path / "ledger.json")
    base.update(overrides)
    return GrowthConfig(**base)


def _ledger(config: GrowthConfig) -> GrowthLedger:
    return GrowthLedger.load(config.ledger_path)


def _disk(config: GrowthConfig) -> dict:
    return json.loads(config.ledger_path.read_text())


def test_skips_accounts_already_followed(tmp_path) -> None:
    config = _config(tmp_path)
    ledger = _ledger(config)
    ledger.record_follow(did="did:plc:a", handle="a.test", uri="at://x", channel="seed", score=1, mode="seed", via=[], followed_at="t")
    client = FakeClient()
    candidates = [_cand("did:plc:a", "a.test"), _cand("did:plc:b", "b.test", following=True), _cand("did:plc:c", "c.test")]

    summary = run_follow_drip(client, candidates, ledger, config, mode="discover", logger=_LOGGER, sleeper=lambda s: None)

    assert client.followed == ["did:plc:c"]
    assert summary.followed == 1
    assert summary.skipped_already == 2
    assert summary.handles == ["c.test"]
    assert set(_disk(config)["follows"]) == {"did:plc:a", "did:plc:c"}
    assert _disk(config)["follows"]["did:plc:c"]["channel"] == "seed_follows"
    assert len(_disk(config)["runs"]) == 1


def test_dry_run_writes_nothing(tmp_path) -> None:
    config = _config(tmp_path)
    client = FakeClient()
    sleeps: list[float] = []
    candidates = [_cand("did:plc:a", "a.test"), _cand("did:plc:b", "b.test")]

    summary = run_follow_drip(client, candidates, _ledger(config), config, mode="discover", dry_run=True, logger=_LOGGER, sleeper=sleeps.append)

    assert client.followed == []
    assert sleeps == []
    assert summary.planned == 2 and summary.followed == 0
    assert summary.handles == ["a.test", "b.test"]
    assert not config.ledger_path.exists()


def test_ledger_is_written_before_every_pacing_sleep(tmp_path) -> None:
    config = _config(tmp_path)
    client = FakeClient()
    seen_at_sleep: list[set[str]] = []

    def sleeper(seconds: float) -> None:
        assert 1.0 <= seconds <= 2.0
        seen_at_sleep.append(set(_disk(config)["follows"]))

    candidates = [_cand("did:plc:a", "a.test"), _cand("did:plc:b", "b.test"), _cand("did:plc:c", "c.test")]
    summary = run_follow_drip(
        client, candidates, _ledger(config), config, mode="discover", logger=_LOGGER, sleeper=sleeper, rng=random.Random(1)
    )

    assert summary.followed == 3
    # No sleep before the first follow, one before each later follow — and at
    # each sleep the previous follow is already on disk.
    assert seen_at_sleep == [{"did:plc:a"}, {"did:plc:a", "did:plc:b"}]


def test_limit_caps_follows(tmp_path) -> None:
    config = _config(tmp_path, follows_per_run=10)
    client = FakeClient()
    candidates = [_cand(f"did:plc:{i}", f"{i}.test") for i in range(5)]

    summary = run_follow_drip(client, candidates, _ledger(config), config, mode="discover", limit=2, logger=_LOGGER, sleeper=lambda s: None)

    assert summary.followed == 2
    assert client.followed == ["did:plc:0", "did:plc:1"]


def test_rate_limit_aborts_and_keeps_state(tmp_path) -> None:
    config = _config(tmp_path)
    client = FakeClient(fail={"did:plc:b": GrowthClientError("slow down", status=429)})
    candidates = [_cand("did:plc:a", "a.test"), _cand("did:plc:b", "b.test"), _cand("did:plc:c", "c.test")]

    summary = run_follow_drip(client, candidates, _ledger(config), config, mode="discover", logger=_LOGGER, sleeper=lambda s: None)

    assert summary.aborted == "rate limited"
    assert summary.followed == 1 and summary.failed == 1
    assert client.followed == ["did:plc:a"]
    assert set(_disk(config)["follows"]) == {"did:plc:a"}
    assert _disk(config)["runs"][-1]["aborted"] == "rate limited"


def test_consecutive_failures_abort_but_single_failure_continues(tmp_path) -> None:
    config = _config(tmp_path, follows_per_run=10)
    err = GrowthClientError("pds hiccup", status=500)
    client = FakeClient(fail={"did:plc:b": err, "did:plc:d": err, "did:plc:e": err, "did:plc:f": err})
    candidates = [_cand(f"did:plc:{h}", f"{h}.test") for h in "abcdefg"]

    summary = run_follow_drip(client, candidates, _ledger(config), config, mode="discover", logger=_LOGGER, sleeper=lambda s: None)

    assert client.followed == ["did:plc:a", "did:plc:c"]
    assert summary.failed == 4
    assert summary.aborted == "3 consecutive failures"


def test_growth_package_has_no_delete_or_batch_write_path() -> None:
    """Follows are permanent by design: no unfollow, no delete, no applyWrites
    (which can carry deletes) anywhere in src/growth."""
    forbidden = ("deleteRecord", "applyWrites", "com.atproto.repo.delete", "deleteAccount")
    sources = sorted(_GROWTH_DIR.glob("*.py"))
    assert sources, "growth package missing"
    for path in sources:
        text = path.read_text(encoding="utf-8")
        for token in forbidden:
            assert token not in text, f"{path.name} contains {token}"


def test_ledger_round_trip_and_run_history_cap(tmp_path) -> None:
    path = tmp_path / "ledger.json"
    ledger = GrowthLedger.load(path)
    ledger.record_follow(did="did:plc:a", handle="a", uri="u", channel="lists", score=0.8, mode="discover", via=["list x"], followed_at="t")
    for i in range(95):
        ledger.append_run({"i": i})
    ledger.pinned_thread = {"hash": "h", "pinned": True}
    ledger.save()

    again = GrowthLedger.load(path)
    assert again.is_followed("did:plc:a")
    assert again.followed_dids() == {"did:plc:a"}
    assert len(again.data["runs"]) == 90
    assert again.data["runs"][0] == {"i": 5}
    assert again.pinned_thread == {"hash": "h", "pinned": True}
