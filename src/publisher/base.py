from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(slots=True)
class PublishResult:
    success: bool
    platform: str
    external_id: str | None = None
    url: str | None = None
    error: str | None = None
    # AT Protocol content hash of the created record; needed alongside the uri
    # to build reply refs when chaining thread posts.
    cid: str | None = None


class Publisher(Protocol):
    def publish(
        self,
        post: str,
        source_link: str | None = None,
        image_path: str | None = None,
        image_alt: str | None = None,
    ) -> PublishResult:
        ...
