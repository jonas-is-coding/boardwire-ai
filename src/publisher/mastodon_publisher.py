from __future__ import annotations

from pathlib import Path

import requests

from src.publisher._common import compose_text_with_link, request_with_retry
from src.publisher.base import PublishResult

# Mastodon's default status limit is 500 characters. Instances may allow more,
# but 500 is the safe lower bound that works everywhere.
_CHAR_LIMIT = 500


class MastodonPublisher:
    platform = "mastodon"

    def __init__(self, base_url: str, access_token: str) -> None:
        self.base_url = base_url.rstrip("/")
        self.access_token = access_token

    def _headers(self) -> dict:
        return {"Authorization": f"Bearer {self.access_token}"}

    def publish(
        self,
        post: str,
        source_link: str | None = None,
        image_path: str | None = None,
        image_alt: str | None = None,
    ) -> PublishResult:
        text = compose_text_with_link(post, source_link, _CHAR_LIMIT)

        try:
            media_ids: list[str] = []
            if image_path:
                path = Path(image_path)
                if not path.exists() or not path.is_file():
                    return PublishResult(
                        success=False,
                        platform=self.platform,
                        error=f"Card image not found: {image_path}",
                    )
                mime = "image/jpeg" if path.suffix.lower() in {".jpg", ".jpeg"} else "image/png"
                try:
                    with path.open("rb") as fh:
                        upload_resp = request_with_retry(
                            "POST",
                            f"{self.base_url}/api/v2/media",
                            headers=self._headers(),
                            files={"file": (path.name, fh, mime)},
                            data={"description": (image_alt or "Boardwire news card")[:1500]},
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
                        error=f"Mastodon media upload failed: {upload_resp.status_code}",
                    )
                media_id = upload_resp.json().get("id")
                if not media_id:
                    return PublishResult(
                        success=False,
                        platform=self.platform,
                        error="Mastodon media upload response missing id",
                    )
                media_ids.append(str(media_id))

            payload: dict = {"status": text}
            if media_ids:
                payload["media_ids[]"] = media_ids

            create_resp = request_with_retry(
                "POST",
                f"{self.base_url}/api/v1/statuses",
                headers=self._headers(),
                data=payload,
                timeout=30,
            )
            if create_resp.status_code >= 400:
                return PublishResult(
                    success=False,
                    platform=self.platform,
                    error=f"Mastodon post failed: {create_resp.status_code}",
                )

            body = create_resp.json()
            return PublishResult(
                success=True,
                platform=self.platform,
                external_id=str(body.get("id")) if body.get("id") else None,
                url=body.get("url"),
            )
        except requests.RequestException as exc:
            return PublishResult(
                success=False,
                platform=self.platform,
                error=f"Mastodon request error: {exc}",
            )
