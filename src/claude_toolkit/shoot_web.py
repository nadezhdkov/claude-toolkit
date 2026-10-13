"""Browser capture for ``ctk shoot web``, run as a script under ``uv run --with playwright``.

Never imported by ``ctk`` itself (Playwright is not a runtime dependency).
Reads one JSON argument, takes a deterministic screenshot and prints a JSON
result. Exit 10 means Playwright's browser is not installed.
"""

import json
import sys

FREEZE_CSS = """
*, *::before, *::after {
  animation: none !important;
  transition: none !important;
  caret-color: transparent !important;
  scroll-behavior: auto !important;
}
"""
BROWSER_MISSING = 10


def main() -> int:
    options = json.loads(sys.argv[1])
    from playwright.sync_api import Error, sync_playwright

    console: list[str] = []
    page_errors: list[str] = []
    with sync_playwright() as playwright:
        try:
            browser = playwright.chromium.launch()
        except Error as error:
            if "Executable doesn't exist" in str(error) or "playwright install" in str(error):
                return BROWSER_MISSING
            raise
        context = browser.new_context(
            viewport={"width": options["width"], "height": options["height"]},
            device_scale_factor=options["scale"],
            color_scheme=options["color_scheme"],
            reduced_motion="reduce",
            locale="en-US",
            timezone_id="UTC",
        )
        page = context.new_page()
        page.on("console", lambda message: message.type == "error" and console.append(message.text[:300]))
        page.on("pageerror", lambda error: page_errors.append(str(error)[:300]))
        timeout = options["timeout"] * 1000
        status = None
        try:
            response = page.goto(options["url"], wait_until="networkidle", timeout=timeout)
            status = response.status if response else None
        except Error as error:
            if "Timeout" not in str(error):
                print(json.dumps({"error": str(error).splitlines()[0]}))
                return 1
            # networkidle never came (polling, websockets): capture what is there.
        page.add_style_tag(content=FREEZE_CSS)
        if options["wait_for"]:
            page.wait_for_selector(options["wait_for"], timeout=timeout)
        page.evaluate("document.fonts ? document.fonts.ready.then(() => true) : true")
        if options["delay"]:
            page.wait_for_timeout(options["delay"])
        page.screenshot(
            path=options["out"],
            full_page=options["full_page"],
            animations="disabled",
            caret="hide",
            mask=[page.locator(selector) for selector in options["mask_selectors"]],
            mask_color="#FF00FF",
        )
        browser.close()
    print(json.dumps({"status": status, "console_errors": console, "page_errors": page_errors}))
    return 0


if __name__ == "__main__":
    sys.exit(main())
