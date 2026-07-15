from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
import time

import requests

from src.composer import LINK_PREFIX, byte_len, shorten_at_word_boundary
from src.publisher.base import PublishResult


def _compose_text_with_link(post: str, source_link: str | None) -> tuple[str, list[dict]]:
    """Return (text, facets) with the source URL appended and a link facet covering it.

    Keeps the combined text within Bluesky's 300-byte conservative budget
    (300 graphemes is the real limit; bytes are the stricter bound and match
    the byte-offset facet indices). The composer already budgets the body so
    this normally appends without trimming; if the body is still too long the
    trim happens at a word boundary — never mid-word — and only as a last
    resort. The URL is never trimmed so the link stays clickable.
    """
    base = post.rstrip()
    if not source_link:
        return shorten_at_word_boundary(base, 300), []

    url = source_link.strip()
    suffix = f"{LINK_PREFIX}{url}"
    budget = 300 - byte_len(suffix)
    if budget < 0:
        return url[:300], []

    if byte_len(base) > budget:
        base = shorten_at_word_boundary(base, budget)

    text = f"{base}{suffix}" if base else url
    byte_end = byte_len(text)
    byte_start = byte_end - byte_len(url)
    facets = [
        {
            "index": {"byteStart": byte_start, "byteEnd": byte_end},
            "features": [
                {"$type": "app.bsky.richtext.facet#link", "uri": url}
            ],
        }
    ]
    return text, facets


@dataclass(slots=True)
class ThreadPost:
    """One post inside a 2-3 post thread."""

    post: str
    source_link: str | None = None
    image_path: str | None = None
    image_alt: str | None = None


@dataclass(slots=True)
class ThreadPublishResult:
    """Outcome of a thread publish.

    ``results`` holds one PublishResult per successfully created post, in
    order. When ``success`` is False and ``results`` is non-empty the thread
    was partially published — callers must record that state so the posts are
    not published again.
    """

    success: bool
    platform: str
    results: list[PublishResult] = field(default_factory=list)
    error: str | None = None

    @property
    def uris(self) -> list[str]:
        return [r.external_id for r in self.results if r.external_id]


def build_reply_ref(root: PublishResult, parent: PublishResult) -> dict:
    """Build the ``reply`` record field chaining a post under root/parent."""
    return {
        "root": {"uri": root.external_id, "cid": root.cid},
        "parent": {"uri": parent.external_id, "cid": parent.cid},
    }


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

    def _create_session(self) -> tuple[str, str] | PublishResult:
        """Return (access_jwt, did) or a failed PublishResult."""
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
        return access_jwt, did

    def _upload_image(self, access_jwt: str, image_path: str) -> dict | PublishResult:
        """Upload a card image; return the blob dict or a failed PublishResult."""
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
        return blob

    def _create_record(self, access_jwt: str, did: str, record: dict) -> PublishResult:
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
            cid=payload.get("cid"),
        )

    def _build_record(
        self,
        access_jwt: str,
        post: str,
        source_link: str | None,
        image_path: str | None,
        image_alt: str | None,
        reply: dict | None = None,
    ) -> dict | PublishResult:
        text, facets = _compose_text_with_link(post, source_link)
        now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
        record: dict = {
            "$type": "app.bsky.feed.post",
            "text": text,
            "createdAt": now,
        }
        if facets:
            record["facets"] = facets
        if reply:
            record["reply"] = reply
        if image_path:
            blob = self._upload_image(access_jwt, image_path)
            if isinstance(blob, PublishResult):
                return blob
            record["embed"] = {
                "$type": "app.bsky.embed.images",
                "images": [
                    {
                        "alt": (image_alt or "Boardwire news card")[:1000],
                        "image": blob,
                    }
                ],
            }
        return record

    def publish(
        self,
        post: str,
        source_link: str | None = None,
        image_path: str | None = None,
        image_alt: str | None = None,
    ) -> PublishResult:
        if not image_path:
            return PublishResult(
                success=False,
                platform=self.platform,
                error="Bluesky image is required but no image_path was provided",
            )

        try:
            session = self._create_session()
            if isinstance(session, PublishResult):
                return session
            access_jwt, did = session

            record = self._build_record(access_jwt, post, source_link, image_path, image_alt)
            if isinstance(record, PublishResult):
                return record

            return self._create_record(access_jwt, did, record)
        except requests.RequestException as exc:
            return PublishResult(success=False, platform=self.platform, error=f"Bluesky request error: {exc}")

    def publish_thread(self, posts: list[ThreadPost]) -> ThreadPublishResult:
        """Publish a reply-chained thread of 2-3 posts.

        Each createRecord response's uri+cid is captured and used as
        ``reply: {root, parent}`` on the next post. If post N fails, the rest
        is aborted and the partial results are returned so the caller can
        record which posts already exist and avoid double-posting.
        """
        if not posts:
            return ThreadPublishResult(success=False, platform=self.platform, error="Empty thread")

        results: list[PublishResult] = []
        try:
            session = self._create_session()
            if isinstance(session, PublishResult):
                return ThreadPublishResult(success=False, platform=self.platform, error=session.error)
            access_jwt, did = session

            for idx, thread_post in enumerate(posts):
                reply = build_reply_ref(root=results[0], parent=results[-1]) if results else None
                record = self._build_record(
                    access_jwt,
                    thread_post.post,
                    thread_post.source_link,
                    thread_post.image_path,
                    thread_post.image_alt,
                    reply=reply,
                )
                if isinstance(record, PublishResult):
                    return ThreadPublishResult(
                        success=False,
                        platform=self.platform,
                        results=results,
                        error=f"Thread post {idx + 1} failed: {record.error}",
                    )
                result = self._create_record(access_jwt, did, record)
                if not result.success:
                    return ThreadPublishResult(
                        success=False,
                        platform=self.platform,
                        results=results,
                        error=f"Thread post {idx + 1} failed: {result.error}",
                    )
                results.append(result)

            return ThreadPublishResult(success=True, platform=self.platform, results=results)
        except requests.RequestException as exc:
            return ThreadPublishResult(
                success=False,
                platform=self.platform,
                results=results,
                error=f"Bluesky request error: {exc}",
            )
