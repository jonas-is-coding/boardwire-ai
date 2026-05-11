from __future__ import annotations

from src.publisher.base import PublishResult


class DryRunPublisher:
    platform = "dry_run"

    def publish(
        self,
        post: str,
        source_link: str | None = None,
        image_path: str | None = None,
    ) -> PublishResult:
        _ = (post, source_link, image_path)
        return PublishResult(success=True, platform=self.platform)
