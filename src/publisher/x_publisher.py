from __future__ import annotations

try:
    import tweepy
except ImportError:  # pragma: no cover - runtime dependency guard
    tweepy = None

from src.publisher.base import PublishResult


class XPublisher:
    platform = "x"

    def __init__(
        self,
        consumer_key: str,
        consumer_secret: str,
        access_token: str,
        access_token_secret: str,
    ) -> None:
        self.consumer_key = consumer_key
        self.consumer_secret = consumer_secret
        self.access_token = access_token
        self.access_token_secret = access_token_secret

    def publish(
        self,
        post: str,
        source_link: str | None = None,
        image_path: str | None = None,
        image_alt: str | None = None,
    ) -> PublishResult:
        if tweepy is None:
            return PublishResult(
                success=False,
                platform=self.platform,
                error="tweepy is not installed. Run: pip install -r requirements.txt",
            )

        _ = image_alt
        text = post if not source_link else f"{post}\n🔗 {source_link}"
        text = text[:280]

        if image_path:
            # Keep this explicit until v1 media upload support is implemented.
            print("[INFO] X media upload not enabled yet, posting text-only")

        try:
            client = tweepy.Client(
                consumer_key=self.consumer_key,
                consumer_secret=self.consumer_secret,
                access_token=self.access_token,
                access_token_secret=self.access_token_secret,
            )
            resp = client.create_tweet(text=text)
            tweet_id = None
            if getattr(resp, "data", None):
                tweet_id = resp.data.get("id")

            url = None
            if tweet_id:
                # Handle can be changed by the user, so use canonical i/web URL.
                url = f"https://x.com/i/web/status/{tweet_id}"

            return PublishResult(
                success=True,
                platform=self.platform,
                external_id=str(tweet_id) if tweet_id else None,
                url=url,
            )
        except Exception as exc:  # pragma: no cover - network/provider dependent
            return PublishResult(
                success=False,
                platform=self.platform,
                error=f"X publish failed: {exc}",
            )
