#!/usr/bin/env python3
import math
import os
import struct
import zlib

OUT_DIR = "desktop-tauri-macos/src-tauri/icons"
os.makedirs(OUT_DIR, exist_ok=True)


def clamp(v, lo=0, hi=255):
    return lo if v < lo else hi if v > hi else v


def pack_png(path, w, h, buf):
    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    raw = bytearray()
    stride = w * 4
    for y in range(h):
        raw.append(0)
        raw.extend(buf[y * stride:(y + 1) * stride])

    ihdr = struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0)
    idat = zlib.compress(bytes(raw), 9)

    with open(path, "wb") as f:
        f.write(b"\x89PNG\r\n\x1a\n")
        f.write(chunk(b"IHDR", ihdr))
        f.write(chunk(b"IDAT", idat))
        f.write(chunk(b"IEND", b""))


def blend_px(buf, w, h, x, y, sr, sg, sb, sa):
    if x < 0 or y < 0 or x >= w or y >= h or sa <= 0:
        return
    i = (y * w + x) * 4
    dr, dg, db, da = buf[i], buf[i + 1], buf[i + 2], buf[i + 3]

    out_a = sa + (da * (255 - sa) + 127) // 255
    if out_a <= 0:
        buf[i:i + 4] = b"\x00\x00\x00\x00"
        return

    num_r = sr * sa * 255 + dr * da * (255 - sa)
    num_g = sg * sa * 255 + dg * da * (255 - sa)
    num_b = sb * sa * 255 + db * da * (255 - sa)

    out_r = clamp((num_r + out_a * 127) // (out_a * 255))
    out_g = clamp((num_g + out_a * 127) // (out_a * 255))
    out_b = clamp((num_b + out_a * 127) // (out_a * 255))

    buf[i] = out_r
    buf[i + 1] = out_g
    buf[i + 2] = out_b
    buf[i + 3] = out_a


def inside_rounded_rect(x, y, x0, y0, ww, hh, rr):
    x1 = x0 + ww - 1
    y1 = y0 + hh - 1
    if x < x0 or x > x1 or y < y0 or y > y1:
        return False
    if x0 + rr <= x <= x1 - rr or y0 + rr <= y <= y1 - rr:
        return True

    cx = x0 + rr if x < x0 + rr else x1 - rr
    cy = y0 + rr if y < y0 + rr else y1 - rr
    dx = x - cx
    dy = y - cy
    return dx * dx + dy * dy <= rr * rr


def fill_rounded_gradient(buf, w, h, x0, y0, ww, hh, rr, c1, c2):
    den = max(1, (ww - 1) + (hh - 1))
    for y in range(y0, y0 + hh):
        for x in range(x0, x0 + ww):
            if not inside_rounded_rect(x, y, x0, y0, ww, hh, rr):
                continue
            t = ((x - x0) + ((y0 + hh - 1) - y)) / den
            t = 0.0 if t < 0.0 else 1.0 if t > 1.0 else t
            r = int(c1[0] * t + c2[0] * (1.0 - t))
            g = int(c1[1] * t + c2[1] * (1.0 - t))
            b = int(c1[2] * t + c2[2] * (1.0 - t))
            blend_px(buf, w, h, x, y, r, g, b, 255)


def fill_circle(buf, w, h, cx, cy, rad, color):
    r2 = rad * rad
    x0 = int(cx - rad)
    x1 = int(cx + rad)
    y0 = int(cy - rad)
    y1 = int(cy + rad)
    cr, cg, cb, ca = color
    for y in range(y0, y1 + 1):
        dy = y - cy
        for x in range(x0, x1 + 1):
            dx = x - cx
            if dx * dx + dy * dy <= r2:
                blend_px(buf, w, h, x, y, cr, cg, cb, ca)


def fill_ellipse(buf, w, h, cx, cy, rx, ry, color):
    x0 = int(cx - rx)
    x1 = int(cx + rx)
    y0 = int(cy - ry)
    y1 = int(cy + ry)
    cr, cg, cb, ca = color
    rx2 = rx * rx
    ry2 = ry * ry
    for y in range(y0, y1 + 1):
        dy2 = (y - cy) * (y - cy)
        for x in range(x0, x1 + 1):
            dx2 = (x - cx) * (x - cx)
            if dx2 / rx2 + dy2 / ry2 <= 1.0:
                blend_px(buf, w, h, x, y, cr, cg, cb, ca)


def fill_rounded_rect(buf, w, h, x0, y0, ww, hh, rr, color):
    cr, cg, cb, ca = color
    for y in range(y0, y0 + hh):
        for x in range(x0, x0 + ww):
            if inside_rounded_rect(x, y, x0, y0, ww, hh, rr):
                blend_px(buf, w, h, x, y, cr, cg, cb, ca)


def fill_ring_sector(buf, w, h, cx, cy, r_in, r_out, a0_deg, a1_deg, color):
    cr, cg, cb, ca = color
    a0 = math.radians(a0_deg)
    a1 = math.radians(a1_deg)
    x0 = int(cx - r_out)
    x1 = int(cx + r_out)
    y0 = int(cy - r_out)
    y1 = int(cy + r_out)
    rin2 = r_in * r_in
    rout2 = r_out * r_out

    for y in range(y0, y1 + 1):
        dy = y - cy
        for x in range(x0, x1 + 1):
            dx = x - cx
            d2 = dx * dx + dy * dy
            if d2 < rin2 or d2 > rout2:
                continue
            ang = math.atan2(dy, dx)
            if a0 <= ang <= a1:
                blend_px(buf, w, h, x, y, cr, cg, cb, ca)


def fill_heart(buf, w, h, cx, cy, size, color):
    cr, cg, cb, ca = color
    half = int(size)
    x0 = int(cx - half)
    x1 = int(cx + half)
    y0 = int(cy - half)
    y1 = int(cy + half)
    for y in range(y0, y1 + 1):
        ny = (y - cy) / float(size)
        for x in range(x0, x1 + 1):
            nx = (x - cx) / float(size)
            # implicit heart curve: (x^2 + y^2 - 1)^3 - x^2*y^3 <= 0
            v = (nx * nx + ny * ny - 1.0) ** 3 - (nx * nx) * (ny ** 3)
            if v <= 0:
                blend_px(buf, w, h, x, y, cr, cg, cb, ca)


def gen_base_png(path, size=1024):
    w = h = size
    buf = bytearray(w * h * 4)

    # background card
    fill_rounded_gradient(buf, w, h, 40, 40, 944, 944, 210, (13, 108, 238), (7, 172, 190))

    # soft glow
    fill_ellipse(buf, w, h, 510, 505, 290, 290, (255, 255, 255, 56))

    # bikini top (cartoon icon)
    fill_ellipse(buf, w, h, 430, 560, 115, 96, (255, 133, 178, 255))
    fill_ellipse(buf, w, h, 594, 560, 115, 96, (255, 133, 178, 255))
    fill_ellipse(buf, w, h, 430, 560, 78, 66, (255, 182, 208, 210))
    fill_ellipse(buf, w, h, 594, 560, 78, 66, (255, 182, 208, 210))
    fill_circle(buf, w, h, 512, 560, 32, (255, 230, 238, 255))
    fill_rounded_rect(buf, w, h, 372, 470, 280, 26, 13, (255, 205, 225, 240))
    fill_rounded_rect(buf, w, h, 372, 642, 280, 24, 12, (247, 89, 147, 255))
    fill_circle(buf, w, h, 340, 560, 18, (255, 170, 201, 230))
    fill_circle(buf, w, h, 684, 560, 18, (255, 170, 201, 230))

    # sea wave accents
    fill_ring_sector(buf, w, h, 512, 340, 240, 270, 210, 330, (224, 249, 255, 235))
    fill_ring_sector(buf, w, h, 512, 315, 275, 302, 210, 330, (224, 249, 255, 180))
    fill_ring_sector(buf, w, h, 512, 296, 305, 328, 212, 328, (204, 243, 255, 150))

    # heart sparkle
    fill_heart(buf, w, h, 742, 732, 34, (255, 232, 130, 230))
    fill_heart(buf, w, h, 278, 700, 24, (255, 232, 130, 185))

    # tiny accents
    fill_circle(buf, w, h, 246, 672, 13, (255, 223, 98, 220))
    fill_circle(buf, w, h, 744, 780, 10, (255, 232, 130, 180))

    pack_png(path, w, h, buf)


def write_simple_ico_from_png(png_path, ico_path):
    with open(png_path, "rb") as f:
        png = f.read()
    # ICO with one 256x256 PNG frame
    header = struct.pack("<HHH", 0, 1, 1)
    entry = struct.pack("<BBBBHHII", 0, 0, 0, 0, 1, 32, len(png), 6 + 16)
    with open(ico_path, "wb") as f:
        f.write(header)
        f.write(entry)
        f.write(png)


def run(cmd):
    code = os.system(cmd)
    if code != 0:
        raise RuntimeError(f"命令失败: {cmd}")


def main():
    base = os.path.join(OUT_DIR, "icon-base-1024.png")
    gen_base_png(base)

    # sizes used by tauri config
    run(f"sips -s format png -z 32 32 {base} --out {os.path.join(OUT_DIR, '32x32.png')} >/dev/null")
    run(f"sips -s format png -z 128 128 {base} --out {os.path.join(OUT_DIR, '128x128.png')} >/dev/null")
    run(f"sips -s format png -z 256 256 {base} --out {os.path.join(OUT_DIR, '128x128@2x.png')} >/dev/null")
    run(f"sips -s format png -z 512 512 {base} --out {os.path.join(OUT_DIR, 'icon.png')} >/dev/null")

    iconset = os.path.join(OUT_DIR, "icon.iconset")
    os.makedirs(iconset, exist_ok=True)
    mapping = {
        "icon_16x16.png": 16,
        "icon_16x16@2x.png": 32,
        "icon_32x32.png": 32,
        "icon_32x32@2x.png": 64,
        "icon_128x128.png": 128,
        "icon_128x128@2x.png": 256,
        "icon_256x256.png": 256,
        "icon_256x256@2x.png": 512,
        "icon_512x512.png": 512,
        "icon_512x512@2x.png": 1024,
    }
    for name, sz in mapping.items():
        run(f"sips -s format png -z {sz} {sz} {base} --out {os.path.join(iconset, name)} >/dev/null")

    run(f"iconutil -c icns {iconset} -o {os.path.join(OUT_DIR, 'icon.icns')}")
    write_simple_ico_from_png(os.path.join(iconset, "icon_256x256.png"), os.path.join(OUT_DIR, "icon.ico"))
    print("ICONS_OK")


if __name__ == "__main__":
    main()
