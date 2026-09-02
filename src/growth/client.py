"""Authenticated AT Protocol client for the growth package.

Scope is deliberately narrow: session creation, graph/profile READS carrying
the authenticated ``viewer`` state (``viewer.following`` is what makes the
follow drip idempotent), and exactly three WRITE shapes — a follow record, the
profile record, and a feed post for the intro thread.

There is no delete path of any kind in this module or anywhere else in
``src/growth``; ``tests/test_growth_follower.py`` scans the package source for
the delete and batch-write XRPC names to keep it that way.
"""

from __future__ import annotations

import time
from datetime import datetime, timezone
from logging import Logger
from typing import Any, Callable

import requests

PDS_URL = "https://bsky.social"
# Unauthenticated AppView: same reads, but no ``viewer`` state and no writes.
PUBLIC_APPVIEW_URL = "https://public.api.bsky.app"

FOLLOW_COLLECTION = "app.bsky.graph.follow"
POST_COLLECTION = "app.bsky.feed.post"
PROFILE_COLLECTION = "app.bsky.actor.profile"

# The only record collections this client will ever write. Checked on every
# write so a future edit cannot quietly widen the scope.
_WRITABLE_COLLECTIONS = frozenset({FOLLOW_COLLECTION, POST_COLLECTION, PROFILE_COLLECTION})

# getProfiles accepts at most 25 actors per request; graph endpoints page at 100.
_PROFILES_PER_CALL = 25
_PAGE_SIZE = 100
_RETRY_ATTEMPTS = 3
_RETRY_DELAY_SECONDS = 2.0
_TIMEOUT_SECONDS = 30


def utc_now_iso(now: datetime | None = None) -> str:
    dt = now or datetime.now(timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


class GrowthClientError(RuntimeError):
    """Any failed XRPC call. ``status`` is the HTTP status (None for transport
    errors); ``error`` the AT Protocol error name when the PDS sent one."""

    def __init__(self, message: str, status: int | None = None, error: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.error = error

    @property
    def rate_limited(self) -> bool:
        return self.status == 429


class GrowthClient:
    def __init__(
        self,
        handle: str,
        app_password: str,
        *,
        logger: Logger,
        pds_url: str = PDS_URL,
        sleeper: Callable[[float], None] = time.sleep,
        public: bool = False,
    ) -> None:
        self.handle = str(handle or "").strip().lstrip("@")
        self._app_password = app_password
        self._logger = logger
        self._pds_url = pds_url.rstrip("/")
        self._sleep = sleeper
        self._public = public
        self.access_jwt: str | None = None
        self.did: str | None = None

    @classmethod
    def public_reader(cls, *, logger: Logger, sleeper: Callable[[float], None] = time.sleep) -> "GrowthClient":
        """Credential-free reader against the public AppView.

        Same graph/profile reads, but profile views carry no ``viewer`` state
        (so "already following" is unknown) and every write is refused. Used
        for ``--growth-verify-seeds`` when no app password is configured.
        """
        return cls("", "", logger=logger, pds_url=PUBLIC_APPVIEW_URL, sleeper=sleeper, public=True)

    @property
    def is_public(self) -> bool:
        return self._public

    # ------------------------------------------------------------------
    # transport
    # ------------------------------------------------------------------

    def _url(self, nsid: str) -> str:
        return f"{self._pds_url}/xrpc/{nsid}"

    def _request(
        self,
        method: str,
        nsid: str,
        *,
        params: Any = None,
        json: dict | None = None,
        auth: bool = True,
    ) -> dict:
        headers: dict[str, str] = {}
        if self._public:
            if method != "GET":
                raise GrowthClientError(f"{nsid}: public reader cannot write")
        elif auth:
            if not self.access_jwt:
                raise GrowthClientError(f"{nsid}: not logged in")
            headers["Authorization"] = f"Bearer {self.access_jwt}"

        delay = _RETRY_DELAY_SECONDS
        for attempt in range(_RETRY_ATTEMPTS):
            last_attempt = attempt == _RETRY_ATTEMPTS - 1
            try:
                if method == "GET":
                    resp = requests.get(self._url(nsid), params=params, headers=headers, timeout=_TIMEOUT_SECONDS)
                else:
                    resp = requests.post(self._url(nsid), json=json, headers=headers, timeout=_TIMEOUT_SECONDS)
            except requests.RequestException as exc:
                self._logger.warning("Bluesky %s request error (attempt %d): %s", nsid, attempt + 1, exc)
                if last_attempt or method != "GET":
                    # A write that timed out may have landed; never blindly retry it.
                    raise GrowthClientError(f"{nsid}: request error: {exc}") from exc
                self._sleep(delay)
                delay *= 2
                continue

            if resp.status_code >= 500 and method == "GET" and not last_attempt:
                self._logger.warning("Bluesky %s returned %d (attempt %d)", nsid, resp.status_code, attempt + 1)
                self._sleep(delay)
                delay *= 2
                continue

            if resp.status_code >= 400:
                error_name, message = _error_details(resp)
                detail = f" {error_name}" if error_name else ""
                detail += f": {message}" if message else ""
                raise GrowthClientError(
                    f"{nsid} failed with {resp.status_code}{detail}",
                    status=resp.status_code,
                    error=error_name,
                )
            if not resp.content:
                return {}
            try:
                body = resp.json()
            except ValueError as exc:
                raise GrowthClientError(f"{nsid}: non-JSON response") from exc
            return body if isinstance(body, dict) else {}
        raise GrowthClientError(f"{nsid}: exhausted retries")  # pragma: no cover - loop always returns/raises

    # ------------------------------------------------------------------
    # session
    # ------------------------------------------------------------------

    def login(self) -> str:
        if self._public:
            raise GrowthClientError("public reader has no session to create")
        body = self._request(
            "POST",
            "com.atproto.server.createSession",
            json={"identifier": self.handle, "password": self._app_password},
            auth=False,
        )
        access_jwt = body.get("accessJwt")
        did = body.get("did")
        if not access_jwt or not did:
            raise GrowthClientError("Bluesky auth response missing accessJwt/did")
        self.access_jwt = str(access_jwt)
        self.did = str(did)
        resolved = body.get("handle")
        if isinstance(resolved, str) and resolved.strip():
            self.handle = resolved.strip()
        return self.did

    # ------------------------------------------------------------------
    # reads (authenticated: profile views carry ``viewer``)
    # ------------------------------------------------------------------

    def get_profile(self, actor: str) -> dict:
        return self._request("GET", "app.bsky.actor.getProfile", params={"actor": actor})

    def get_profiles(self, actors: list[str]) -> list[dict]:
        """Detailed profile views for up to any number of actors, batched by 25."""
        profiles: list[dict] = []
        for start in range(0, len(actors), _PROFILES_PER_CALL):
            batch = actors[start : start + _PROFILES_PER_CALL]
            body = self._request("GET", "app.bsky.actor.getProfiles", params=[("actors", a) for a in batch])
            profiles.extend(p for p in body.get("profiles", []) if isinstance(p, dict))
        return profiles

    def _paginate(self, nsid: str, params: dict[str, str], key: str, limit: int) -> list[dict]:
        items: list[dict] = []
        cursor: str | None = None
        max_pages = max(1, limit // _PAGE_SIZE + 2)
        for _ in range(max_pages):
            if len(items) >= limit:
                break
            page_params = dict(params)
            page_params["limit"] = str(min(_PAGE_SIZE, limit - len(items)))
            if cursor:
                page_params["cursor"] = cursor
            body = self._request("GET", nsid, params=page_params)
            page = body.get(key, [])
            if not isinstance(page, list) or not page:
                break
            items.extend(x for x in page if isinstance(x, dict))
            cursor = body.get("cursor")
            if not cursor:
                break
        return items[:limit]

    def get_follows(self, actor: str, limit: int = _PAGE_SIZE) -> list[dict]:
        return self._paginate("app.bsky.graph.getFollows", {"actor": actor}, "follows", limit)

    def get_followers(self, actor: str, limit: int = _PAGE_SIZE) -> list[dict]:
        return self._paginate("app.bsky.graph.getFollowers", {"actor": actor}, "followers", limit)

    def get_list_members(self, list_uri: str, limit: int = _PAGE_SIZE) -> list[dict]:
        items = self._paginate("app.bsky.graph.getList", {"list": list_uri}, "items", limit)
        return [item["subject"] for item in items if isinstance(item.get("subject"), dict)]

    def search_actors(self, query: str, limit: int = 50) -> list[dict]:
        return self._paginate("app.bsky.actor.searchActors", {"q": query}, "actors", limit)

    def get_starter_pack(self, uri: str) -> dict:
        """``starterPack`` view for an ``at://.../app.bsky.graph.starterpack/...`` URI."""
        body = self._request("GET", "app.bsky.graph.getStarterPack", params={"starterPack": uri})
        pack = body.get("starterPack")
        return pack if isinstance(pack, dict) else {}

    def get_list_info(self, list_uri: str) -> dict:
        """``list`` view (name, purpose, listItemCount) without the members."""
        body = self._request("GET", "app.bsky.graph.getList", params={"list": list_uri, "limit": "1"})
        info = body.get("list")
        return info if isinstance(info, dict) else {}

    def latest_post_at(self, actor: str, max_pages: int = 3) -> str | None:
        """``createdAt`` of the actor's newest original post, or None.

        Reposts sit in the same feed (with a ``reason``) and are skipped, so
        the feed is paged — a run of reposts on top must not hide the real
        last post and make an active account look dormant.
        """
        cursor: str | None = None
        for _ in range(max(1, max_pages)):
            params = {"actor": actor, "limit": "10", "filter": "posts_no_replies"}
            if cursor:
                params["cursor"] = cursor
            body = self._request("GET", "app.bsky.feed.getAuthorFeed", params=params)
            feed = body.get("feed") or []
            for item in feed:
                if not isinstance(item, dict) or item.get("reason"):
                    continue  # reposts carry a ``reason`` and someone else's createdAt
                post = item.get("post") or {}
                record = post.get("record") or {}
                created = record.get("createdAt") or post.get("indexedAt")
                if created:
                    return str(created)
            cursor = body.get("cursor")
            if not cursor or not feed:
                break
        return None

    def list_records(self, collection: str, limit: int = 50) -> list[dict]:
        """Newest-first ``{uri, cid, value}`` records of our own repo in ``collection``."""
        body = self._request(
            "GET",
            "com.atproto.repo.listRecords",
            params={
                "repo": self.did or self.handle,
                "collection": collection,
                "limit": str(max(1, min(100, limit))),
                "reverse": "true",
            },
        )
        records = body.get("records")
        return [r for r in records if isinstance(r, dict)] if isinstance(records, list) else []

    def get_record(self, collection: str, rkey: str, repo: str | None = None) -> dict | None:
        """``{uri, cid, value}`` for a record in our repo, or None if it does not exist."""
        try:
            return self._request(
                "GET",
                "com.atproto.repo.getRecord",
                params={"repo": repo or self.did or self.handle, "collection": collection, "rkey": rkey},
            )
        except GrowthClientError as exc:
            not_found = exc.error == "RecordNotFound" or "could not locate record" in str(exc).lower()
            if exc.status in {400, 404} and not_found:
                return None
            raise

    # ------------------------------------------------------------------
    # writes (create / put only)
    # ------------------------------------------------------------------

    def _create_record(self, collection: str, record: dict) -> dict:
        if collection not in _WRITABLE_COLLECTIONS:
            raise GrowthClientError(f"refusing to write collection {collection}")
        return self._request(
            "POST",
            "com.atproto.repo.createRecord",
            json={"repo": self.did, "collection": collection, "record": record},
        )

    def follow(self, did: str, now: datetime | None = None) -> dict:
        """Create a permanent follow record for ``did``. Returns ``{uri, cid}``."""
        if not str(did).startswith("did:"):
            raise GrowthClientError(f"follow subject must be a DID, got {did!r}")
        record = {"$type": FOLLOW_COLLECTION, "subject": did, "createdAt": utc_now_iso(now)}
        return self._create_record(FOLLOW_COLLECTION, record)

    def create_post(self, record: dict) -> dict:
        return self._create_record(POST_COLLECTION, record)

    def put_record(self, collection: str, rkey: str, record: dict, swap_record: str | None = None) -> dict:
        if collection not in _WRITABLE_COLLECTIONS:
            raise GrowthClientError(f"refusing to write collection {collection}")
        body: dict[str, Any] = {"repo": self.did, "collection": collection, "rkey": rkey, "record": record}
        if swap_record:
            body["swapRecord"] = swap_record
        return self._request("POST", "com.atproto.repo.putRecord", json=body)


def _error_details(resp: requests.Response) -> tuple[str | None, str | None]:
    try:
        body = resp.json()
    except ValueError:
        return None, None
    if not isinstance(body, dict):
        return None, None
    error = body.get("error")
    message = body.get("message")
    return (str(error) if error else None, str(message) if message else None)
