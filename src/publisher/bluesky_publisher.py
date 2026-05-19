from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import time

import requests

from src.publisher.base import PublishResult


def _compose_text_with_link(post: str, source_link: str | None) -> tuple[str, list[dict]]:
    """Return (text, facets) with the source URL appended and a link facet covering it.

    Keeps the combined text within Bluesky's 300 grapheme/byte limit by trimming
    the post body — never the URL — so the link stays clickable.
    """
    base = post.rstrip()
    if not source_link:
        return base[:300], []

    url = source_link.strip()
    separator = "\n\n"
    suffix = f"{separator}🔗 {url}"
    budget = 300 - len(suffix.encode("utf-8"))
    if budget < 0:
        return url[:300], []

    body_bytes = base.encode("utf-8")
    if len(body_bytes) > budget:
        trimmed = body_bytes[:budget].decode("utf-8", errors="ignore").rstrip()
        base = trimmed

    text = f"{base}{suffix}" if base else url
    text_bytes = text.encode("utf-8")
    url_bytes = url.encode("utf-8")
    byte_end = len(text_bytes)
    byte_start = byte_end - len(url_bytes)
    facets = [
        {
            "index": {"byteStart": byte_start, "byteEnd": byte_end},
            "features": [
                {"$type": "app.bsky.richtext.facet#link", "uri": url}
            ],
        }
    ]
    return text, facets


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
        text, facets = _compose_text_with_link(post, source_link)

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
            if facets:
                record["facets"] = facets

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
