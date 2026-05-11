from __future__ import annotations

import time
from pathlib import Path

from playwright.sync_api import TimeoutError as PlaywrightTimeoutError
from playwright.sync_api import sync_playwright

from src.publisher.base import PublishResult


class XBrowserPublisher:
    platform = "x_browser"

    def __init__(self, profile_dir: Path, auto_click_post: bool = False) -> None:
        self.profile_dir = profile_dir
        self.auto_click_post = auto_click_post

    def publish(
        self,
        post: str,
        source_link: str | None = None,
        image_path: str | None = None,
        image_alt: str | None = None,
    ) -> PublishResult:
        _ = image_alt
        text = post if not source_link else f"{post}\n🔗 {source_link}"
        text = text[:280]

        try:
            self.profile_dir.mkdir(parents=True, exist_ok=True)
            with sync_playwright() as p:
                context = p.chromium.launch_persistent_context(
                    user_data_dir=str(self.profile_dir),
                    headless=False,
                    viewport={"width": 1280, "height": 900},
                )
                page = context.new_page()
                page.goto("https://x.com/compose/post", wait_until="domcontentloaded", timeout=60000)

                # Give user a moment for login/challenge screens if needed.
                print("[INFO] Open browser and log in if needed")
                time.sleep(2)

                composer = page.locator('div[role="textbox"][data-testid="tweetTextarea_0"]')
                composer.wait_for(state="visible", timeout=120000)
                composer.click()
                composer.fill(text)

                if image_path:
                    path = Path(image_path)
                    if path.exists() and path.is_file():
                        file_input = page.locator('input[data-testid="fileInput"]')
                        file_input.set_input_files(str(path))
                    else:
                        print(f"[WARNING] Image path not found for x_browser: {image_path}")

                if self.auto_click_post:
                    post_button = page.locator('button[data-testid="tweetButtonInline"]')
                    post_button.wait_for(state="visible", timeout=30000)
                    post_button.click()
                    time.sleep(2)
                    context.close()
                    return PublishResult(
                        success=True,
                        platform=self.platform,
                        external_id=None,
                        url=None,
                    )

                print("[INFO] Post prepared for manual confirmation")
                # Keep browser open for manual click.
                time.sleep(20)
                context.close()
                return PublishResult(
                    success=False,
                    platform=self.platform,
                    error="Post prepared for manual confirmation (not auto-clicked)",
                )
        except PlaywrightTimeoutError as exc:
            return PublishResult(
                success=False,
                platform=self.platform,
                error=f"x_browser timed out waiting for composer/login: {exc}",
            )
        except Exception as exc:  # pragma: no cover - local GUI/runtime dependent
            return PublishResult(
                success=False,
                platform=self.platform,
                error=f"x_browser publish failed: {exc}",
            )
