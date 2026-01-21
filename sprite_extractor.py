#!/usr/bin/env python3
"""
sprite_extractor.py

Flood fill connected components on a downscaled occupancy mask (tile-sized)
using 8-connectivity, then crop and mask out pixels not in the component.

Inputs:
- A sprite sheet image (PNG recommended). If it has alpha, alpha>0 is foreground.
  Otherwise foreground is any pixel not equal to the most common RGB value.

Outputs:
- One PNG per extracted component: sprite_0000.png, sprite_0001.png, ...
- atlas.json describing each sprite crop and mask bounds.

Example:
  python3 sprite_extractor.py sheet.png --out out --tile 2
"""

from __future__ import annotations

import argparse
import json
import os
from collections import Counter, deque
from dataclasses import dataclass
from typing import Deque, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from PIL import Image


@dataclass(frozen=True)
class SpriteRecord:
    id: int
    name: str
    x: int
    y: int
    w: int
    h: int
    mask_x: int
    mask_y: int
    mask_w: int
    mask_h: int
    image: str


def send_to_vlm(image_path: str) -> str:
    """
    Placeholder for a vision-language model labeler.
    Replace with a real call if desired.

    Must return a short label string for the sprite.
    """
    return os.path.splitext(os.path.basename(image_path))[0]


def most_common_rgb(img: Image.Image) -> Tuple[int, int, int]:
    px = img.convert("RGB").load()
    w, h = img.size
    step = 1 if w * h <= 2_000_000 else 2
    c = Counter(px[x, y] for y in range(0, h, step) for x in range(0, w, step))
    return c.most_common(1)[0][0] if c else (0, 0, 0)


def foreground_mask(img: Image.Image) -> List[List[bool]]:
    w, h = img.size
    if "A" in img.getbands():
        px = img.convert("RGBA").load()
        return [[px[x, y][3] > 0 for x in range(w)] for y in range(h)]

    bg = most_common_rgb(img)
    px = img.convert("RGB").load()
    return [[px[x, y] != bg for x in range(w)] for y in range(h)]


def downscale_any(mask: Sequence[Sequence[bool]], tile: int) -> Tuple[List[List[bool]], int, int]:
    h = len(mask)
    w = len(mask[0]) if h else 0
    sw = (w + tile - 1) // tile
    sh = (h + tile - 1) // tile

    small = [[False] * sw for _ in range(sh)]
    for sy in range(sh):
        y0, y1 = sy * tile, min((sy + 1) * tile, h)
        for sx in range(sw):
            x0, x1 = sx * tile, min((sx + 1) * tile, w)
            small[sy][sx] = any(mask[y][x] for y in range(y0, y1) for x in range(x0, x1))
    return small, sw, sh


def flood_components_8(small: Sequence[Sequence[bool]]) -> List[List[Tuple[int, int]]]:
    sh = len(small)
    sw = len(small[0]) if sh else 0
    vis = [[False] * sw for _ in range(sh)]
    comps: List[List[Tuple[int, int]]] = []

    nbrs = [
        (dx, dy)
        for dy in (-1, 0, 1)
        for dx in (-1, 0, 1)
        if not (dx == 0 and dy == 0)
    ]

    for y in range(sh):
        for x in range(sw):
            if not small[y][x] or vis[y][x]:
                continue

            q: Deque[Tuple[int, int]] = deque([(x, y)])
            vis[y][x] = True
            cells: List[Tuple[int, int]] = []

            while q:
                cx, cy = q.popleft()
                cells.append((cx, cy))
                for dx, dy in nbrs:
                    nx, ny = cx + dx, cy + dy
                    if 0 <= nx < sw and 0 <= ny < sh and small[ny][nx] and not vis[ny][nx]:
                        vis[ny][nx] = True
                        q.append((nx, ny))

            comps.append(cells)

    return comps


def sort_components(
    comps: List[List[Tuple[int, int]]],
    mode: str,
) -> List[List[Tuple[int, int]]]:
    if mode == "none":
        return comps

    def bbox_key(cells: List[Tuple[int, int]]) -> Tuple[int, int, int, int]:
        xs = [x for x, _ in cells]
        ys = [y for _, y in cells]
        return (min(ys), min(xs), max(ys), max(xs))

    def size_key(cells: List[Tuple[int, int]]) -> int:
        return -len(cells)

    if mode == "topleft":
        return sorted(comps, key=bbox_key)
    if mode == "size":
        return sorted(comps, key=size_key)
    raise ValueError(f"Unknown sort mode: {mode}")


def apply_component_mask(
    rgba: Image.Image,
    full_mask: List[List[bool]],
    cell_set: Set[Tuple[int, int]],
    tile: int,
    crop_box: Tuple[int, int, int, int],
) -> Image.Image:
    x0, y0, x1, y1 = crop_box
    crop = rgba.crop((x0, y0, x1, y1))
    cp = crop.load()
    cw, ch = crop.size

    for py in range(ch):
        gy = y0 + py
        sy = gy // tile
        row_m = full_mask[gy]
        for px in range(cw):
            gx = x0 + px
            sx = gx // tile
            if (sx, sy) not in cell_set or not row_m[gx]:
                r, g, b, _a = cp[px, py]
                cp[px, py] = (r, g, b, 0)

    return crop


def extract_sprites(
    in_path: str,
    out_dir: str,
    tile: int,
    sort_mode: str,
    min_cells: int,
    label: bool,
) -> Tuple[Dict, List[SpriteRecord]]:
    os.makedirs(out_dir, exist_ok=True)

    img = Image.open(in_path)
    rgba = img.convert("RGBA")
    w, h = rgba.size

    m = foreground_mask(img)
    small, sw, sh = downscale_any(m, tile)
    comps = flood_components_8(small)
    comps = [c for c in comps if len(c) >= min_cells]
    comps = sort_components(comps, sort_mode)

    sprites: List[SpriteRecord] = []
    for sid, cells in enumerate(comps):
        cell_set = set(cells)

        xs = [x for x, _ in cells]
        ys = [y for _, y in cells]
        sx0, sy0, sx1, sy1 = min(xs), min(ys), max(xs) + 1, max(ys) + 1

        x0, y0 = sx0 * tile, sy0 * tile
        x1, y1 = min(sx1 * tile, w), min(sy1 * tile, h)

        crop = apply_component_mask(
            rgba=rgba,
            full_mask=m,
            cell_set=cell_set,
            tile=tile,
            crop_box=(x0, y0, x1, y1),
        )

        out_img = f"sprite_{sid:04d}.png"
        out_path = os.path.join(out_dir, out_img)
        crop.save(out_path)

        name = send_to_vlm(out_path) if label else out_img

        sprites.append(
            SpriteRecord(
                id=sid,
                name=name,
                x=x0,
                y=y0,
                w=x1 - x0,
                h=y1 - y0,
                mask_x=sx0,
                mask_y=sy0,
                mask_w=sx1 - sx0,
                mask_h=sy1 - sy0,
                image=out_img,
            )
        )

    atlas = {
        "meta": {
            "source": os.path.basename(in_path),
            "image_w": w,
            "image_h": h,
            "tile": tile,
            "mask_w": sw,
            "mask_h": sh,
            "count": len(sprites),
        },
        "sprites": [s.__dict__ for s in sprites],
    }

    return atlas, sprites


def build_argparser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="sprite_extractor.py",
        description="Extract connected components from a sprite sheet using a downscaled occupancy mask.",
    )
    p.add_argument("input", help="Path to input sprite sheet image (e.g. sheet.png).")
    p.add_argument("--out", default="out", help="Output directory. Default: out")
    p.add_argument("--tile", type=int, default=2, help="Downscale tile size in pixels. Default: 2")
    p.add_argument("--atlas", default="atlas.json", help="Atlas JSON filename inside --out. Default: atlas.json")
    p.add_argument(
        "--sort",
        choices=["none", "topleft", "size"],
        default="topleft",
        help="Component ordering in output. Default: topleft",
    )
    p.add_argument(
        "--min-cells",
        type=int,
        default=1,
        help="Drop components smaller than this many mask-cells. Default: 1",
    )
    p.add_argument(
        "--no-label",
        action="store_true",
        help="Do not call the labeler; use the output filename as the name.",
    )
    return p


def main(argv: Optional[Sequence[str]] = None) -> int:
    args = build_argparser().parse_args(argv)

    if args.tile <= 0:
        raise SystemExit("--tile must be >= 1")
    if args.min_cells <= 0:
        raise SystemExit("--min-cells must be >= 1")

    atlas, sprites = extract_sprites(
        in_path=args.input,
        out_dir=args.out,
        tile=args.tile,
        sort_mode=args.sort,
        min_cells=args.min_cells,
        label=not args.no_label,
    )

    atlas_path = os.path.join(args.out, args.atlas)
    with open(atlas_path, "w", encoding="utf-8") as f:
        json.dump(atlas, f, indent=2)

    print(f"sprites: {len(sprites)}")
    print(f"wrote:   {atlas_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
