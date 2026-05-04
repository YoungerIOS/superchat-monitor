#!/usr/bin/env python3
"""将 `src-tauri/icons/icon-reference-xchat.png`（须为 1024×1024）写入 `icon-base-1024.png`。

常见情况：设计里留了透明边，但导出成 PNG 时变成 **RGB + 纯黑边**（无 alpha）。脚本会从四边向内做 flood-fill，
把与边缘连通的 **近黑色** 像素改为透明，避免程序坞/桌面里出现黑块。

若四角已是透明（alpha 很低），则跳过该步骤，避免误伤。

其它尺寸：``npx @tauri-apps/cli icon src-tauri/icons/icon-base-1024.png``
"""

from __future__ import annotations

from collections import deque
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
REF = ROOT / "src-tauri" / "icons" / "icon-reference-xchat.png"
OUT = ROOT / "src-tauri" / "icons" / "icon-base-1024.png"
SIZE = 1024

# 与画布边缘连通、且 RGB 和低于此阈值的视为「本应透明」的黑边（含轻微抗锯齿）
NEAR_BLACK_SUM = 32
NEAR_BLACK_ALPHA_MIN = 240


def corners_already_transparent(im: Image.Image) -> bool:
    im = im.convert("RGBA")
    px = im.load()
    w, h = im.size
    for c in (px[0, 0], px[w - 1, 0], px[0, h - 1], px[w - 1, h - 1]):
        if c[3] < 64:
            return True
    return False


def solid_black_margins_to_transparent(im: Image.Image) -> Image.Image:
    """把与图像边缘 4-连通、且近黑不透明的区域改为透明。"""
    im = im.convert("RGBA")
    w, h = im.size
    px = im.load()

    def near_margin(c: tuple[int, int, int, int]) -> bool:
        r, g, b, a = c
        if a < NEAR_BLACK_ALPHA_MIN:
            return False
        return r + g + b < NEAR_BLACK_SUM

    q: deque[tuple[int, int]] = deque()
    seen: set[tuple[int, int]] = set()

    def try_seed(x: int, y: int) -> None:
        if not (0 <= x < w and 0 <= y < h):
            return
        if (x, y) in seen or not near_margin(px[x, y]):
            return
        seen.add((x, y))
        q.append((x, y))

    for x in range(w):
        try_seed(x, 0)
        try_seed(x, h - 1)
    for y in range(h):
        try_seed(0, y)
        try_seed(w - 1, y)

    while q:
        x, y = q.popleft()
        for dx, dy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < w and 0 <= ny < h) or (nx, ny) in seen:
                continue
            if not near_margin(px[nx, ny]):
                continue
            seen.add((nx, ny))
            q.append((nx, ny))

    out = im.copy()
    p2 = out.load()
    for x, y in seen:
        p2[x, y] = (0, 0, 0, 0)
    return out


def main() -> None:
    if not REF.is_file():
        raise SystemExit(f"缺少参考图: {REF}")
    im = Image.open(REF)
    if im.size != (SIZE, SIZE):
        raise SystemExit(f"参考图须为 {SIZE}×{SIZE}，当前为 {im.size[0]}×{im.size[1]}")
    if not corners_already_transparent(im):
        im = solid_black_margins_to_transparent(im)
    else:
        im = im.convert("RGBA")
    im.save(OUT, "PNG")
    print(f"Wrote {OUT}（自 {REF}，已处理黑边→透明若适用）")


if __name__ == "__main__":
    main()
