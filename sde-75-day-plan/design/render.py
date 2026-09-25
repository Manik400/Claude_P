"""Render mockup.html to the design PNGs, light and dark.

    ..\\..\\Profile_Naukri_Screener-main\\.venv\\Scripts\\python.exe render.py

Writes design/png/<theme>-<view>.png. Needs Playwright (already in the
Naukri screener's venv) and its Chromium.
"""
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
OUT = HERE / "png"
VIEWS = {
    "desktop": {"width": 1440, "height": 900, "full": False},
    "mcal": {"width": 390, "height": 844, "full": True},
    "mday": {"width": 390, "height": 844, "full": True},
    "mstats": {"width": 390, "height": 844, "full": True},
}


def main():
    OUT.mkdir(exist_ok=True)
    url = (HERE / "mockup.html").as_uri()
    with sync_playwright() as p:
        browser = p.chromium.launch()
        for theme in ("light", "dark"):
            for view, v in VIEWS.items():
                page = browser.new_page(viewport={"width": v["width"], "height": v["height"]},
                                        device_scale_factor=2, color_scheme=theme)
                page.goto(f"{url}?view={view}&theme={theme}" + ("&shot=1" if v["full"] else ""))
                page.wait_for_timeout(300)
                path = OUT / f"{theme}-{view}.png"
                page.screenshot(path=str(path), full_page=v["full"])
                page.close()
                print(path)
        browser.close()


if __name__ == "__main__":
    main()
