from __future__ import annotations

import json
from pathlib import Path

from src import main as main_mod
from src.growth import settings as settings_mod
from src.growth.client import GrowthClientError


def _creds(monkeypatch) -> None:
    monkeypatch.setenv("BLUESKY_HANDLE", "boardwire.bsky.social")
    monkeypatch.setenv("BLUESKY_APP_PASSWORD", "app-pw")
    monkeypatch.delenv("BOARDWIRE_REAL_PUBLISH_ENABLED", raising=False)


class FakeClient:
    instances: list["FakeClient"] = []

    def __init__(self, handle: str, app_password: str, *, logger, **kwargs) -> None:
        self.handle = handle
        self.did: str | None = None
        self.logged_in = False
        self.follows: list[str] = []
        FakeClient.instances.append(self)

    def login(self) -> str:
        self.logged_in = True
        self.did = "did:plc:me"
        return self.did

    def get_profiles(self, actors: list[str]) -> list[dict]:
        return [
            {
                "did": "did:plc:seed",
                "handle": "seed.test",
                "description": "MCP builder",
                "followersCount": 100,
                "followsCount": 10,
                "postsCount": 50,
                "viewer": {},
            }
        ]

    def get_profile(self, actor: str) -> dict:
        raise GrowthClientError("Profile not found", status=400)

    def latest_post_at(self, actor: str) -> str | None:
        return "2026-09-01T00:00:00Z"

    def follow(self, did: str, now=None) -> dict:
        self.follows.append(did)
        return {"uri": "at://did:plc:me/app.bsky.graph.follow/1", "cid": "c"}


def _use_fake_client(monkeypatch, tmp_path: Path, seeds: list[str]) -> Path:
    FakeClient.instances.clear()
    monkeypatch.setattr("src.growth.client.GrowthClient", FakeClient)
    config_path = tmp_path / "growth.json"
    ledger_path = tmp_path / "ledger.json"
    config_path.write_text(json.dumps({"seed_handles": seeds, "ledger_path": str(ledger_path), "pace_seconds": [0, 0]}))
    monkeypatch.setattr(settings_mod, "GROWTH_CONFIG_PATH", config_path)
    return ledger_path


def test_growth_requires_credentials(monkeypatch) -> None:
    monkeypatch.delenv("BLUESKY_HANDLE", raising=False)
    monkeypatch.delenv("BLUESKY_APP_PASSWORD", raising=False)
    assert main_mod.run(["--growth-follow", "--growth-dry-run"]) == 1
    assert main_mod.run(["--growth-verify-seeds"]) == 1


def test_growth_refuses_real_writes_without_flag(monkeypatch, tmp_path) -> None:
    _creds(monkeypatch)
    _use_fake_client(monkeypatch, tmp_path, ["seed.test"])
    assert main_mod.run(["--growth-follow"]) == 1
    assert main_mod.run(["--growth-profile"]) == 1
    assert main_mod.run(["--growth-pin-thread"]) == 1
    assert FakeClient.instances == []  # refused before any login


def test_growth_rejects_bad_limit(monkeypatch, tmp_path) -> None:
    _creds(monkeypatch)
    _use_fake_client(monkeypatch, tmp_path, ["seed.test"])
    assert main_mod.run(["--growth-follow", "--growth-dry-run", "--growth-limit", "0"]) == 1


def test_growth_seed_dry_run_plans_without_writing(monkeypatch, tmp_path) -> None:
    _creds(monkeypatch)
    ledger_path = _use_fake_client(monkeypatch, tmp_path, ["seed.test", "ghost.test"])

    assert main_mod.run(["--growth-follow", "--growth-mode", "seed", "--growth-dry-run"]) == 0

    client = FakeClient.instances[-1]
    assert client.logged_in
    assert client.follows == []
    assert not ledger_path.exists()


def test_growth_seed_follow_writes_ledger_when_enabled(monkeypatch, tmp_path) -> None:
    _creds(monkeypatch)
    monkeypatch.setenv("BOARDWIRE_REAL_PUBLISH_ENABLED", "true")
    ledger_path = _use_fake_client(monkeypatch, tmp_path, ["seed.test"])

    assert main_mod.run(["--growth-follow", "--growth-mode", "seed"]) == 0

    assert FakeClient.instances[-1].follows == ["did:plc:seed"]
    assert "did:plc:seed" in json.loads(ledger_path.read_text())["follows"]


def test_growth_verify_seeds_exit_code(monkeypatch, tmp_path) -> None:
    _creds(monkeypatch)
    _use_fake_client(monkeypatch, tmp_path, ["seed.test"])
    assert main_mod.run(["--growth-verify-seeds"]) == 0

    _use_fake_client(monkeypatch, tmp_path, ["seed.test", "ghost.test"])
    assert main_mod.run(["--growth-verify-seeds"]) == 1

    _use_fake_client(monkeypatch, tmp_path, [])
    assert main_mod.run(["--growth-verify-seeds"]) == 1
