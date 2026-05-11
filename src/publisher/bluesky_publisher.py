from __future__ import annotations

from datetime import datetime, timezone

import requests

from src.publisher.base import PublishResult


class BlueskyPublisher:
    platform = "bluesky"

    def __init__(self, handle: str, app_password: str) -> None:
        self.handle = handle
        self.app_password = app_password

    def publish(self, post: str, source_link: str | None = None) -> PublishResult:
        text = post if not source_link else f"{post}\n{source_link}"
        text = text[:300]

        try:
            session_resp = requests.post(
                "https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": self.handle, "password": self.app_password},
                timeout=20,
            )
            if session_resp.status_code >= 400:
                return PublishResult(
                    success=False,
                    platform=self.platform,
                    error=f"Bluesky auth failed: {session_resp.status_code}",
                )

            session = session_resp.json()
            access_jwt = session.get("accessJwt")
            did = session.get("did")
            if not access_jwt or not did:
                return PublishResult(success=False, platform=self.platform, error="Bluesky auth response missing fields")

            now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            create_resp = requests.post(
                "https://bsky.social/xrpc/com.atproto.repo.createRecord",
                headers={"Authorization": f"Bearer {access_jwt}"},
                json={
                    "repo": did,
                    "collection": "app.bsky.feed.post",
                    "record": {
                        "$type": "app.bsky.feed.post",
                        "text": text,
                        "createdAt": now,
                    },
                },
                timeout=20,
            )
            if create_resp.status_code >= 400:
                return PublishResult(
                    success=False,
                    platform=self.platform,
                    error=f"Bluesky post failed: {create_resp.status_code}",
                )

            payload = create_resp.json()
            uri = payload.get("uri")
            return PublishResult(
                success=True,
                platform=self.platform,
                external_id=uri,
                url=uri,
            )
        except requests.RequestException as exc:
            return PublishResult(success=False, platform=self.platform, error=f"Bluesky request error: {exc}")
