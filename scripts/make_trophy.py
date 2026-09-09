#!/usr/bin/env python3
"""Draw the bundled trophy image shown on a top-3 run.

A UI asset, not user media: it ships inside the package
(cli/pauk/tui/assets/trophy.png) and is loaded from disk, so no
upload or network is involved. Re-run to regenerate; commit the
output.
"""

from pathlib import Path

from PIL import Image, ImageDraw

W = H = 240
GOLD = (240, 190, 60)
GOLD_DARK = (200, 150, 30)
GOLD_LIGHT = (255, 225, 130)
BASE = (120, 80, 20)
BG = (24, 26, 32, 0)  # transparent


def main() -> None:
    img = Image.new("RGBA", (W, H), BG)
    d = ImageDraw.Draw(img)

    cx = W // 2

    # cup bowl (a rounded trapezoid)
    d.polygon(
        [(70, 60), (170, 60), (150, 120), (90, 120)],
        fill=GOLD,
    )
    d.ellipse([90, 108, 150, 132], fill=GOLD)          # rounded bottom
    d.ellipse([70, 48, 170, 74], fill=GOLD_LIGHT)       # rim
    d.ellipse([80, 52, 160, 70], fill=GOLD)             # rim inner
    # a little shine
    d.ellipse([98, 62, 116, 100], fill=GOLD_LIGHT)

    # handles
    for sign in (-1, 1):
        x0 = cx + sign * 58
        box = [min(x0, cx + sign * 88), 60, max(x0, cx + sign * 88), 104]
        d.arc(
            [min(box[0], box[2]), box[1], max(box[0], box[2]), box[3]],
            start=(300 if sign < 0 else 60),
            end=(60 if sign < 0 else 300),
            fill=GOLD_DARK, width=8,
        )

    # stem
    d.rectangle([cx - 8, 128, cx + 8, 158], fill=GOLD_DARK)
    # base
    d.polygon([(cx - 34, 186), (cx + 34, 186), (cx + 24, 160), (cx - 24, 160)], fill=GOLD)
    d.rectangle([cx - 46, 186, cx + 46, 200], fill=BASE)

    # a bright "1" on the cup
    d.text((cx - 5, 74), "1", fill=BASE)

    out = Path(__file__).resolve().parents[1] / "cli" / "pauk" / "tui" / "assets" / "trophy.png"
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
