"""Take the README screenshots from the demo page.

Run the demo first (`npm run dev` in frontend/), then from the repo root:

    python frontend/docs/screenshots.py

Each shot loads the demo with `?scenario=…&theme=…&shot`, which hides
everything but the card, renders it in headless Chrome at 2x, trims the page
background and writes a JPEG next to this file. Needs Chrome or Edge and
Pillow (both already on a Home Assistant development machine).
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageChops

HERE = Path(__file__).resolve().parent
DEMO = os.environ.get("PULSE_CHECK_DEMO", "http://127.0.0.1:5173/")

# name, scenario on the demo page, theme
SHOTS = [
    ("batteries", "default", "dark"),
    ("connectivity", "grouped", "light"),
    ("actions", "actions", "dark"),
]

BROWSERS = [
    r"C:\Program Files\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
    r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    "/usr/bin/google-chrome",
    "/usr/bin/chromium",
    "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
]

SCALE = 2
# CSS pixels: the demo's card column is 520 wide with 16 of padding.
WIDTH, HEIGHT = 560, 1800
PAD = 16 * SCALE
JPEG_QUALITY = 88


def browser() -> str:
    """Return the first installed Chrome or Edge."""
    for path in BROWSERS:
        if Path(path).exists():
            return path
    sys.exit("No Chrome or Edge found; edit BROWSERS in this script.")


def capture(exe: str, url: str, out: Path, profile: Path) -> None:
    """Render the page headless at 2x and save a full-window PNG."""
    subprocess.run(
        [
            exe,
            "--headless=new",
            "--disable-gpu",
            "--hide-scrollbars",
            "--no-first-run",
            f"--user-data-dir={profile}",
            f"--force-device-scale-factor={SCALE}",
            f"--window-size={WIDTH},{HEIGHT}",
            # Let the demo's fake subscription and history timers fire.
            "--virtual-time-budget=6000",
            f"--screenshot={out}",
            url,
        ],
        check=True,
        timeout=120,
        capture_output=True,
    )


def trim(png: Path, jpg: Path) -> tuple[int, int]:
    """Crop the PNG to the card plus a margin and save it as a JPEG."""
    image = Image.open(png).convert("RGB")
    background = Image.new("RGB", image.size, image.getpixel((0, 0)))
    box = ImageChops.difference(image, background).getbbox()
    if box is None:
        sys.exit(f"{png}: blank page; is the demo running at {DEMO}?")
    left, top, right, bottom = box
    cropped = image.crop(
        (
            max(0, left - PAD),
            max(0, top - PAD),
            min(image.width, right + PAD),
            min(image.height, bottom + PAD),
        )
    )
    cropped.save(jpg, "JPEG", quality=JPEG_QUALITY, optimize=True)
    return cropped.size


def main() -> None:
    """Take every shot in SHOTS."""
    exe = browser()
    with tempfile.TemporaryDirectory() as tmp:
        for name, scenario, theme in SHOTS:
            png = Path(tmp) / f"{name}.png"
            url = f"{DEMO}?scenario={scenario}&theme={theme}&shot"
            capture(exe, url, png, Path(tmp) / "profile")
            jpg = HERE / f"screenshot-{name}.jpg"
            width, height = trim(png, jpg)
            print(f"{jpg.name}: {width}x{height}, {jpg.stat().st_size // 1024} kB")


if __name__ == "__main__":
    main()
