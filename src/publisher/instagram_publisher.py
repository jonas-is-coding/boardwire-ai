from __future__ import annotations

import requests

from src.publisher._common import compose_text_with_link, public_image_url, request_with_retry
from src.publisher.base import PublishResult

# Instagram captions allow up to 2,200 characters.
_CAPTION_LIMIT = 2200
_DEFAULT_API_VERSION = "v21.0"


class InstagramPublisher:
    """Publish a single image post via the Instagram Graph Content Publishing API.

    Posting is free, but requires a Business/Creator account linked to a Facebook
    Page and a long-lived access token. The Graph API fetches the image by URL,
    so the card must be hosted publicly (``image_base_url``) — it is not uploaded
    as binary like on Bluesky/Mastodon.
    """

    platform = "instagram"

    def __init__(
        self,
        user_id: str,
        access_token: str,
        image_base_url: str,
        api_version: str = _DEFAULT_API_VERSION,
    ) -> None:
        self.user_id = user_id
        self.access_token = access_token
        self.image_base_url = image_base_url
        self.api_version = api_version

    @property
    def _base(self) -> str:
        return f"https://graph.facebook.com/{self.api_version}/{self.user_id}"

    def _permalink(self, media_id: str) -> str | None:
        try:
            resp = request_with_retry(
                "GET",
                f"https://graph.facebook.com/{self.api_version}/{media_id}",
                params={"fields": "permalink", "access_token": self.access_token},
                timeout=30,
            )
            if resp.status_code >= 400:
                return None
            return resp.json().get("permalink")
        except requests.RequestException:
            return None

    def publish(
        self,
        post: str,
        source_link: str | None = None,
        image_path: str | None = None,
        image_alt: str | None = None,
    ) -> PublishResult:
        _ = image_alt  # Instagram has no per-post alt-text field on the publish API.
        if not image_path:
            return PublishResult(
                success=False,
                platform=self.platform,
                error="Instagram image is required but no image_path was provided",
            )
        if not self.image_base_url:
            return PublishResult(
                success=False,
                platform=self.platform,
                error="Instagram requires INSTAGRAM_IMAGE_BASE_URL so the card can be fetched by a public URL",
            )

        caption = compose_text_with_link(post, source_link, _CAPTION_LIMIT)
        image_url = public_image_url(image_path, self.image_base_url)

        try:
            container_resp = request_with_retry(
                "POST",
                f"{self._base}/media",
                data={
                    "image_url": image_url,
                    "caption": caption,
                    "access_token": self.access_token,
                },
                timeout=60,
            )
            if container_resp.status_code >= 400:
                return PublishResult(
                    success=False,
                    platform=self.platform,
                    error=f"Instagram container creation failed: {container_resp.status_code}",
                )
            creation_id = container_resp.json().get("id")
            if not creation_id:
                return PublishResult(
                    success=False,
                    platform=self.platform,
                    error="Instagram container response missing id",
                )

            publish_resp = request_with_retry(
                "POST",
                f"{self._base}/media_publish",
                data={"creation_id": creation_id, "access_token": self.access_token},
                timeout=60,
            )
            if publish_resp.status_code >= 400:
                return PublishResult(
                    success=False,
                    platform=self.platform,
                    error=f"Instagram publish failed: {publish_resp.status_code}",
                )

            media_id = publish_resp.json().get("id")
            if not media_id:
                return PublishResult(
                    success=False,
                    platform=self.platform,
                    error="Instagram publish response missing media id",
                )

            return PublishResult(
                success=True,
                platform=self.platform,
                external_id=str(media_id),
                url=self._permalink(str(media_id)),
            )
        except requests.RequestException as exc:
            return PublishResult(
                success=False,
                platform=self.platform,
                error=f"Instagram request error: {exc}",
            )
