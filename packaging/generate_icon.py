"""Generates the FoulPlay app icon: a play button (movie/video) with a
small checkmark badge (cleaned/verified-safe), in the app's accent color.
Draws at high resolution and downsamples for crisp edges at every size a
Windows .ico needs.

Run with: python packaging/generate_icon.py
Produces: packaging/icon.ico (multi-size) and data/icon.ico (bundled with the app).
"""

from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ACCENT = (59, 111, 224, 255)  # matches app/style.py ACCENT
WHITE = (255, 255, 255, 255)
BADGE_GREEN = (46, 184, 92, 255)

CANVAS_SIZE = 1024
SIZES = [16, 24, 32, 48, 64, 128, 256]

REPO_ROOT = Path(__file__).resolve().parent.parent


def _rounded_square(size: int, fill) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    radius = int(size * 0.22)
    draw.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=fill)
    return img


def build_icon() -> Image.Image:
    img = _rounded_square(CANVAS_SIZE, ACCENT)
    draw = ImageDraw.Draw(img)

    # Play triangle, centered with a slight left bias so the badge has room.
    cx, cy = CANVAS_SIZE * 0.46, CANVAS_SIZE * 0.5
    tri_h = CANVAS_SIZE * 0.42
    tri_w = CANVAS_SIZE * 0.36
    points = [
        (cx - tri_w * 0.4, cy - tri_h / 2),
        (cx - tri_w * 0.4, cy + tri_h / 2),
        (cx + tri_w * 0.6, cy),
    ]
    draw.polygon(points, fill=WHITE)

    # Checkmark badge, bottom-right corner.
    badge_r = CANVAS_SIZE * 0.22
    badge_cx, badge_cy = CANVAS_SIZE * 0.78, CANVAS_SIZE * 0.78
    draw.ellipse(
        [badge_cx - badge_r, badge_cy - badge_r, badge_cx + badge_r, badge_cy + badge_r],
        fill=ACCENT[:3] + (255,),
        outline=WHITE,
        width=int(CANVAS_SIZE * 0.018),
    )
    draw.ellipse(
        [
            badge_cx - badge_r * 0.78,
            badge_cy - badge_r * 0.78,
            badge_cx + badge_r * 0.78,
            badge_cy + badge_r * 0.78,
        ],
        fill=BADGE_GREEN,
    )
    check_w = int(CANVAS_SIZE * 0.028)
    check_points = [
        (badge_cx - badge_r * 0.38, badge_cy + badge_r * 0.02),
        (badge_cx - badge_r * 0.08, badge_cy + badge_r * 0.32),
        (badge_cx + badge_r * 0.42, badge_cy - badge_r * 0.32),
    ]
    draw.line(check_points, fill=WHITE, width=check_w, joint="curve")

    return img


def main() -> None:
    base = build_icon()

    packaging_ico = REPO_ROOT / "packaging" / "icon.ico"
    data_ico = REPO_ROOT / "data" / "icon.ico"

    images = [base.resize((s, s), Image.LANCZOS) for s in SIZES]
    images[-1].save(
        packaging_ico,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=images[:-1],
    )
    images[-1].save(
        data_ico,
        format="ICO",
        sizes=[(s, s) for s in SIZES],
        append_images=images[:-1],
    )

    preview_png = REPO_ROOT / "packaging" / "icon_preview.png"
    base.resize((256, 256), Image.LANCZOS).save(preview_png)

    print(f"Wrote {packaging_ico}")
    print(f"Wrote {data_ico}")
    print(f"Wrote {preview_png}")


if __name__ == "__main__":
    main()
