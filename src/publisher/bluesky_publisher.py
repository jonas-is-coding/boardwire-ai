from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time

import requests

from src.publisher.base import PublishResult


class BlueskyPublisher:
    platform = "bluesky"

    def __init__(self, handle: str, app_password: str) -> None:
        self.handle = handle
        self.app_password = app_password

    def _post_with_retry(self, url: str, **kwargs) -> requests.Response:
        attempts = 3
        delay_seconds = 2
        last_error: Exception | None = None
        for idx in range(attempts):
            try:
                return requests.post(url, **kwargs)
            except requests.Timeout as exc:
                last_error = exc
                if idx == attempts - 1:
                    raise
                time.sleep(delay_seconds)
        if last_error:
            raise last_error
        raise requests.RequestException("Unexpected Bluesky retry failure")

    def publish(
        self,
        post: str,
        source_link: str | None = None,
        image_path: str | None = None,
        image_alt: str | None = None,
    ) -> PublishResult:
        text = post if not source_link else f"{post}\n🔗 {source_link}"
        text = text[:300]

        if not image_path:
            return PublishResult(
                success=False,
                platform=self.platform,
                error="Bluesky image is required but no image_path was provided",
            )

        try:
            session_resp = self._post_with_retry(
                "https://bsky.social/xrpc/com.atproto.server.createSession",
                json={"identifier": self.handle, "password": self.app_password},
                timeout=30,
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
            record: dict = {
                "$type": "app.bsky.feed.post",
                "text": text,
                "createdAt": now,
            }

            path = Path(image_path)
            if not path.exists() or not path.is_file():
                return PublishResult(
                    success=False,
                    platform=self.platform,
                    error=f"Card image not found: {image_path}",
                )

            mime = "image/png"
            if path.suffix.lower() in {".jpg", ".jpeg"}:
                mime = "image/jpeg"
            try:
                image_bytes = path.read_bytes()
                upload_resp = self._post_with_retry(
                    "https://bsky.social/xrpc/com.atproto.repo.uploadBlob",
                    headers={
                        "Authorization": f"Bearer {access_jwt}",
                        "Content-Type": mime,
                    },
                    data=image_bytes,
                    timeout=60,
                )
            except OSError as exc:
                return PublishResult(
                    success=False,
                    platform=self.platform,
                    error=f"Failed reading card image: {exc}",
                )

            if upload_resp.status_code >= 400:
                return PublishResult(
                    success=False,
                    platform=self.platform,
                    error=f"Bluesky image upload failed: {upload_resp.status_code}",
                )

            blob = upload_resp.json().get("blob")
            if not blob:
                return PublishResult(
                    success=False,
                    platform=self.platform,
                    error="Bluesky image upload response missing blob",
                )

            record["embed"] = {
                "$type": "app.bsky.embed.images",
                "images": [
                    {
                        "alt": (image_alt or "Boardwire news card")[:1000],
                        "image": blob,
                    }
                ],
            }

            create_resp = self._post_with_retry(
                "https://bsky.social/xrpc/com.atproto.repo.createRecord",
                headers={"Authorization": f"Bearer {access_jwt}"},
                json={
                    "repo": did,
                    "collection": "app.bsky.feed.post",
                    "record": record,
                },
                timeout=30,
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
