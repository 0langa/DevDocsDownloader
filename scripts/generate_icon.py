"""Generate DevDocsDownloader.ico at multiple resolutions using Pillow."""
from __future__ import annotations

import math
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "desktop" / "DevDocsDownloader.Desktop" / "Assets" / "DevDocsDownloader.ico"

# Palette
BG_DARK = (13, 17, 27)        # #0D111B  deep navy
BG_MID  = (22, 32, 58)        # #16203A  card bg
BLUE    = (59, 130, 246)      # #3B82F6  primary blue
BLUE_LT = (147, 197, 253)     # #93C5FD  light blue accent
WHITE   = (255, 255, 255)
ARROW   = (96, 165, 250)      # #60A5FA


def rounded_rect(draw: ImageDraw.ImageDraw, bbox: tuple[int, int, int, int], radius: int, fill: tuple) -> None:
    x0, y0, x1, y1 = bbox
    draw.rectangle([x0 + radius, y0, x1 - radius, y1], fill=fill)
    draw.rectangle([x0, y0 + radius, x1, y1 - radius], fill=fill)
    draw.ellipse([x0, y0, x0 + 2 * radius, y0 + 2 * radius], fill=fill)
    draw.ellipse([x1 - 2 * radius, y0, x1, y0 + 2 * radius], fill=fill)
    draw.ellipse([x0, y1 - 2 * radius, x0 + 2 * radius, y1], fill=fill)
    draw.ellipse([x1 - 2 * radius, y1 - 2 * radius, x1, y1], fill=fill)


def draw_arrow_down(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: tuple) -> None:
    """Draw a downward chevron arrow centered at (cx, cy)."""
    half = size // 2
    stem_w = max(2, size // 5)
    stem_h = size // 2
    head_h = size - stem_h
    head_w = size

    # Stem
    draw.rectangle(
        [cx - stem_w // 2, cy - half, cx + stem_w // 2, cy - half + stem_h],
        fill=color,
    )
    # Arrowhead triangle
    head_top = cy - half + stem_h
    points = [
        (cx - head_w // 2, head_top),
        (cx + head_w // 2, head_top),
        (cx, cy + half),
    ]
    draw.polygon(points, fill=color)


def draw_code_brackets(draw: ImageDraw.ImageDraw, cx: int, cy: int, size: int, color: tuple, lw: int) -> None:
    """Draw </> using thick lines."""
    gap = size // 4
    bw = size // 3     # bracket width
    bh = size // 2     # bracket height
    tip = size // 5    # inward tip

    # Left bracket <
    lx = cx - gap - bw
    points_l = [
        (lx + bw, cy - bh // 2),
        (lx,      cy),
        (lx + bw, cy + bh // 2),
    ]
    draw.line([points_l[0], points_l[1]], fill=color, width=lw)
    draw.line([points_l[1], points_l[2]], fill=color, width=lw)

    # Right bracket >
    rx = cx + gap
    points_r = [
        (rx,      cy - bh // 2),
        (rx + bw, cy),
        (rx,      cy + bh // 2),
    ]
    draw.line([points_r[0], points_r[1]], fill=color, width=lw)
    draw.line([points_r[1], points_r[2]], fill=color, width=lw)

    # Slash / in middle
    slash_x0 = cx + gap // 2
    slash_x1 = cx - gap // 2
    draw.line(
        [(slash_x0, cy + bh // 2), (slash_x1, cy - bh // 2)],
        fill=color,
        width=lw,
    )


def make_icon(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    pad = max(1, size // 16)
    radius = max(2, size // 6)

    # Background
    rounded_rect(draw, (pad, pad, size - pad - 1, size - pad - 1), radius, BG_DARK)

    if size >= 48:
        # Inner card
        inner_pad = size // 8
        inner_radius = max(2, radius // 2)
        rounded_rect(
            draw,
            (inner_pad, inner_pad, size - inner_pad - 1, size - inner_pad - 1),
            inner_radius,
            BG_MID,
        )

    if size >= 32:
        # </> brackets in upper 60% of icon
        bracket_cx = size // 2
        bracket_cy = int(size * 0.38)
        bracket_size = max(6, int(size * 0.36))
        lw = max(1, size // 20)
        draw_code_brackets(draw, bracket_cx, bracket_cy, bracket_size, WHITE, lw)

        # Download arrow in lower 35% of icon
        arrow_cx = size // 2
        arrow_cy = int(size * 0.72)
        arrow_size = max(4, int(size * 0.26))
        draw_arrow_down(draw, arrow_cx, arrow_cy, arrow_size, ARROW)

        # Thin separator line
        sep_y = int(size * 0.57)
        sep_x0 = size // 5
        sep_x1 = size - size // 5
        draw.line([(sep_x0, sep_y), (sep_x1, sep_y)], fill=(59, 130, 246, 100), width=max(1, size // 64))
    else:
        # Tiny sizes: just a bold downward arrow
        arrow_cx = size // 2
        arrow_cy = size // 2
        arrow_size = max(4, int(size * 0.55))
        draw_arrow_down(draw, arrow_cx, arrow_cy, arrow_size, WHITE)

    return img


def main() -> None:
    OUT.parent.mkdir(parents=True, exist_ok=True)
    sizes = [16, 24, 32, 48, 64, 128, 256]
    frames = [make_icon(s) for s in sizes]
    frames[0].save(
        OUT,
        format="ICO",
        sizes=[(s, s) for s in sizes],
        append_images=frames[1:],
    )
    print(f"[icon] Written {OUT}  ({len(sizes)} resolutions: {sizes})")


if __name__ == "__main__":
    main()
