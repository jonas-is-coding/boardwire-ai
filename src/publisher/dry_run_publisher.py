from __future__ import annotations

import uuid

from src.publisher.base import PublishResult


class DryRunPublisher:
    platform = "dry_run"

    def publish(
        self,
        post: str,
        source_link: str | None = None,
        image_path: str | None = None,
        image_alt: str | None = None,
    ) -> PublishResult:
        _ = (post, source_link, image_path, image_alt)
        return PublishResult(success=True, platform=self.platform)

    def publish_thread(self, posts: list) -> "ThreadPublishResult":
        """Simulate a thread publish with fake uri/cid pairs so the reply-ref
        chaining path is exercised end-to-end without hitting Bluesky."""
        from src.publisher.bluesky_publisher import ThreadPublishResult, build_reply_ref

        results: list[PublishResult] = []
        thread_id = uuid.uuid4().hex[:8]
        for idx, _thread_post in enumerate(posts):
            result = PublishResult(
                success=True,
                platform=self.platform,
                external_id=f"dry-run://thread/{thread_id}/post/{idx + 1}",
                url=f"dry-run://thread/{thread_id}/post/{idx + 1}",
                cid=f"dry-cid-{thread_id}-{idx + 1}",
            )
            if results:
                # Build (and discard) the reply ref exactly like the real
                # publisher, so dry runs validate the chaining inputs.
                build_reply_ref(root=results[0], parent=results[-1])
            results.append(result)
        return ThreadPublishResult(success=bool(results), platform=self.platform, results=results)
