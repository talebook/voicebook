"""用 Chromium 验收 GitHub Pages 报告与完整章节播放器。"""

from __future__ import annotations

import json
import math
from pathlib import Path

from playwright.sync_api import sync_playwright


REPORT_URL = (Path(__file__).resolve().parents[4] / "design/20260716-voicebook-tool.active.html").as_uri()
SCREENSHOT_DIR = Path("/private/tmp/voicebook-tool-pages-qa")


def verify_viewport(page, *, name: str, width: int, height: int) -> dict[str, object]:
    page.set_viewport_size({"width": width, "height": height})
    page.goto(REPORT_URL, wait_until="networkidle", timeout=120_000)
    page.locator("#full-book-demos").scroll_into_view_if_needed()

    assert "ACTIVE" in page.title()
    assert page.locator("#full-book-demos audio").count() == 6
    assert page.locator("#full-book-demos .audio-card").count() == 6

    media = page.locator("#full-book-demos audio").evaluate_all(
        """elements => Promise.all(elements.map(element => new Promise((resolve, reject) => {
          const finish = () => resolve({
            src: element.currentSrc || element.src,
            duration: element.duration,
            readyState: element.readyState,
            networkState: element.networkState
          });
          if (element.readyState >= 1) return finish();
          element.addEventListener('loadedmetadata', finish, {once: true});
          element.addEventListener('error', () => reject(new Error(`音频加载失败: ${element.src}`)), {once: true});
          element.load();
        })))"""
    )
    for item in media:
        assert item["readyState"] >= 1, item
        assert item["networkState"] != 3, item
        assert math.isfinite(item["duration"]) and item["duration"] > 60, item

    layout = page.evaluate(
        """() => ({
          innerWidth: window.innerWidth,
          bodyWidth: document.body.scrollWidth,
          demoVisible: Boolean(document.querySelector('#full-book-demos')?.getBoundingClientRect().height),
          overflowing: Array.from(document.querySelectorAll('*'))
            .map(element => ({element, rect: element.getBoundingClientRect()}))
            .filter(({rect}) => rect.right > window.innerWidth + 1 || rect.left < -1)
            .slice(0, 12)
            .map(({element, rect}) => ({
              tag: element.tagName,
              className: element.className?.baseVal ?? element.className ?? '',
              left: rect.left,
              right: rect.right,
              width: rect.width
            })),
          visibleScrollOverflow: Array.from(document.querySelectorAll('*'))
            .map(element => ({
              element,
              extra: element.scrollWidth - element.clientWidth,
              overflowX: getComputedStyle(element).overflowX
            }))
            .filter(({extra, overflowX}) => extra > 1 && overflowX === 'visible')
            .sort((left, right) => right.extra - left.extra)
            .slice(0, 12)
            .map(({element, extra}) => ({
              tag: element.tagName,
              className: element.className?.baseVal ?? element.className ?? '',
              extra,
              text: (element.textContent ?? '').trim().slice(0, 120)
            }))
        })"""
    )
    assert layout["demoVisible"]
    assert layout["bodyWidth"] <= layout["innerWidth"], layout

    SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
    page.screenshot(path=str(SCREENSHOT_DIR / f"{name}.png"), full_page=True)
    return {"viewport": {"width": width, "height": height}, "layout": layout, "media": media}


def main() -> None:
    console_errors: list[str] = []
    failed_requests: list[str] = []
    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(headless=True, args=["--allow-file-access-from-files"])
        page = browser.new_page()
        page.on("console", lambda message: console_errors.append(message.text) if message.type == "error" else None)
        page.on("requestfailed", lambda request: failed_requests.append(f"{request.url}: {request.failure}"))
        results = [
            verify_viewport(page, name="desktop", width=1440, height=1000),
            verify_viewport(page, name="mobile", width=390, height=844),
        ]
        browser.close()

    # Chromium 读取到足够的本地 MP3 元数据后会主动中止剩余文件读取；
    # readyState、duration 与 networkState 已在上面验证，这类 ERR_ABORTED 是预期行为。
    unexpected_failed_requests = [
        failure
        for failure in failed_requests
        if not (".mp3:" in failure and failure.endswith("net::ERR_ABORTED"))
    ]
    assert not unexpected_failed_requests, unexpected_failed_requests
    assert not console_errors, console_errors
    print(
        json.dumps(
            {
                "status": "passed",
                "expected_media_aborts": len(failed_requests),
                "views": results,
            },
            ensure_ascii=False,
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
