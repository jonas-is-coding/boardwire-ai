from __future__ import annotations

import requests

from src.publisher._common import compose_text_with_link, public_image_url, request_with_retry
from src.publisher.base import PublishResult

# Threads posts allow up to 500 characters.
_TEXT_LIMIT = 500
_DEFAULT_API_VERSION = "v1.0"


class ThreadsPublisher:
    """Publish to Threads via the Meta Threads API (container -> publish).

    Text-only posts are supported, so an image is optional: when an
    ``image_path`` and ``image_base_url`` are both available the post is created
    as an IMAGE container (the API fetches the card by URL), otherwise it falls
    back to a TEXT post.
    """

    platform = "threads"

    def __init__(
        self,
        user_id: str,
        access_token: str,
        image_base_url: str | None = None,
        api_version: str = _DEFAULT_API_VERSION,
    ) -> None:
        self.user_id = user_id
        self.access_token = access_token
        self.image_base_url = image_base_url
        self.api_version = api_version

    @property
    def _base(self) -> str:
        return f"https://graph.threads.net/{self.api_version}/{self.user_id}"

    def _permalink(self, thread_id: str) -> str | None:
        try:
            resp = request_with_retry(
                "GET",
                f"https://graph.threads.net/{self.api_version}/{thread_id}",
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
        _ = image_alt  # Threads has no per-post alt-text field on the publish API.
        text = compose_text_with_link(post, source_link, _TEXT_LIMIT)

        container_data: dict = {"text": text, "access_token": self.access_token}
        if image_path and self.image_base_url:
            container_data["media_type"] = "IMAGE"
            container_data["image_url"] = public_image_url(image_path, self.image_base_url)
        else:
            container_data["media_type"] = "TEXT"

        try:
            container_resp = request_with_retry(
                "POST",
                f"{self._base}/threads",
                data=container_data,
                timeout=60,
            )
            if container_resp.status_code >= 400:
                return PublishResult(
                    success=False,
                    platform=self.platform,
                    error=f"Threads container creation failed: {container_resp.status_code}",
                )
            creation_id = container_resp.json().get("id")
            if not creation_id:
                return PublishResult(
                    success=False,
                    platform=self.platform,
                    error="Threads container response missing id",
                )

            publish_resp = request_with_retry(
                "POST",
                f"{self._base}/threads_publish",
                data={"creation_id": creation_id, "access_token": self.access_token},
                timeout=60,
            )
            if publish_resp.status_code >= 400:
                return PublishResult(
                    success=False,
                    platform=self.platform,
                    error=f"Threads publish failed: {publish_resp.status_code}",
                )

            thread_id = publish_resp.json().get("id")
            if not thread_id:
                return PublishResult(
                    success=False,
                    platform=self.platform,
                    error="Threads publish response missing id",
                )

            return PublishResult(
                success=True,
                platform=self.platform,
                external_id=str(thread_id),
                url=self._permalink(str(thread_id)),
            )
        except requests.RequestException as exc:
            return PublishResult(
                success=False,
                platform=self.platform,
                error=f"Threads request error: {exc}",
            )
