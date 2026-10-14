import pathlib
import sys
import typing

from playwright.sync_api import FloatRect, Page, ViewportSize, sync_playwright

from demo.server import serve


_VIEWPORT: typing.Final = ViewportSize(width=1200, height=760)
_CLIP: typing.Final = FloatRect(x=0, y=0, width=1200, height=668)


def capture(page: Page, url: str, output: pathlib.Path) -> None:
    page.set_viewport_size(_VIEWPORT)
    page.goto(f"{url}#issues=SHOP-38")
    page.locator("details.service .chip:visible").first.wait_for()
    page.screenshot(path=output, clip=_CLIP)


def main(site: pathlib.Path) -> None:
    with serve(site) as url, sync_playwright() as playwright:
        browser: typing.Final = playwright.chromium.launch()
        page: typing.Final = browser.new_page(device_scale_factor=2, color_scheme="light", locale="en-US")
        capture(page, url, site / "screenshot.png")
        browser.close()


if __name__ == "__main__":
    main(pathlib.Path(sys.argv[1] if len(sys.argv) > 1 else "site"))
