# -*- coding: utf-8 -*-
"""
"Скажи мне, что всё это чушь..." — вечер, окно в исчезающий город.
Процедурная гравюра: индиго-вечер, рваные чёрные тени, расщелина
в мироздании, город, расшивающийся в пунктир и утягиваемый в дыру.

Чистая stdlib. Полный детерминизм: свой LCG-хеш, никаких случайных
источников, никакого времени. Два запуска — идентичные байты.
"""

import zlib
import struct
import os
from math import sin, cos, pi, sqrt, floor

W = 1024
H = 1024

# ---------------------------------------------------------------- детерминизм


def hash2(ix, iy, k=0):
    n = (ix * 374761393 + iy * 668265263 + k * 2246822519) & 0x7FFFFFFF
    n = ((n ^ (n >> 13)) * 1274126177) & 0xFFFFFFFF
    n = (n ^ (n >> 16)) & 0xFFFFFFFF
    return n / 4294967296.0


def hash3(ix, iy, k=0):
    """[-0.5, 0.5) — центрированный шум."""
    return hash2(ix, iy, k) - 0.5


def smooth(t):
    return t * t * (3.0 - 2.0 * t)


def vnoise(x, y, k=0):
    ix, iy = floor(x), floor(y)
    fx, fy = x - ix, y - iy
    ux, uy = smooth(fx), smooth(fy)
    a = hash2(ix, iy, k)
    b = hash2(ix + 1, iy, k)
    c = hash2(ix, iy + 1, k)
    d = hash2(ix + 1, iy + 1, k)
    return a + (b - a) * ux + (c - a) * uy + (a - b - c + d) * ux * uy


def fbm(x, y, octaves=4, k=0):
    v = 0.0
    amp = 0.5
    f = 1.0
    tot = 0.0
    for o in range(octaves):
        v += amp * vnoise(x * f, y * f, k + o * 131)
        tot += amp
        f *= 2.0
        amp *= 0.5
    return v / tot  # ~[0,1)


def clamp(v, a, b):
    return a if v < a else (b if v > b else v)


def lerp(a, b, t):
    return a + (b - a) * t


def mix(c1, c2, t):
    t = clamp(t, 0.0, 1.0)
    return (lerp(c1[0], c2[0], t), lerp(c1[1], c2[1], t), lerp(c1[2], c2[2], t))


# ---------------------------------------------------------------- палитра

SKY_LOW = (96, 84, 104)     # мёртвый пепел с розовым, у горизонта
SKY_MID = (34, 38, 68)      # индиго вечера
SKY_TOP = (7, 8, 18)        # чернота неба
AMBER = (208, 142, 62)      # живые окна
INK = (5, 5, 9)             # чернильная чернота комнаты
FAR_C = (58, 62, 92)        # дальний план в тумане
MID_C = (22, 24, 44)        # средний план
NEAR_C = (9, 10, 18)        # ближний план — почти чернила
FOG = (74, 78, 106)

# ---------------------------------------------------------------- город


def build_layer(seed, base_y, max_h, min_h):
    """План города: список зданий (x0, x1, h, kind, aux)."""
    s = seed
    def rnd():
        nonlocal s
        s = (16807 * s) % 2147483647
        return s / 2147483647.0

    bld = []
    x = -60.0
    while x < W + 60:
        w = 34 + rnd() * 100
        h = min_h + rnd() * (max_h - min_h)
        kind = "flat"
        aux = 0.0
        r = rnd()
        if r < 0.28:
            kind = "peak"
        elif r < 0.52:
            kind = "chim"
            aux = x + w * (0.15 + rnd() * 0.7)
        bld.append((x, x + w, h, kind, aux))
        x += w + 4 + rnd() * 30
    return bld


def city_top_at(px, bld):
    """Верх силуэта в колонке px; -1 если улица."""
    top = -1
    for (x0, x1, h, kind, aux) in bld:
        if x0 <= px <= x1:
            if kind == "peak":
                t = (px - x0) / (x1 - x0)
                roof = h * (1.06 - abs(t - 0.5) * 1.5)
            elif kind == "chim" and abs(px - aux) < 7:
                roof = h * 1.22
            else:
                roof = h
            if base_top(roof) > top:
                top = base_top(roof)
    return top


BASE = {}  # base_y по слою передаём через замыкание — здесь просто кэш


def base_top(h):
    return h  # высоты уже абсолютные (top от низа кадра), вернём как есть


# ---------------------------------------------------------------- render


def render():
    img = bytearray(W * H * 3)

    # абсолютные высоты верхушек (от низа кадра)
    far = [(x0, x1, 596 - h, kind, aux) for (x0, x1, h, kind, aux) in
           build_layer(101, 0, 240, 100)]
    mid = [(x0, x1, 690 - h, kind, aux) for (x0, x1, h, kind, aux) in
           build_layer(202, 0, 380, 150)]
    near = [(x0, x1, 810 - h, kind, aux) for (x0, x1, h, kind, aux) in
           build_layer(303, 0, 560, 230)]

    # окно: конкретное, с вертикальной перекладиной
    FX0, FY0, FX1, FY1 = 118.0, 64.0, 906.0, 872.0
    MULLION = 512.0  # перекладина, слегка наклонена — рисуем полосой

    # расщелина: рваная кривая от верха окна вниз, кривизна + шум
    def rift_x(py):
        t = (py - FY0) / (FY1 - FY0)          # 0 верх .. 1 низ
        cx = 716 + sin(t * 2.2) * 55          # изгиб; правее перекладины
        cx += (fbm(t * 3.0, 4.7, 4, 61) - 0.5) * 150
        return cx, t

    def rift_w(t):
        # ширина расщелины: шире кверху, с пульсацией и дрожью
        pulse = 1.0 + 0.45 * sin(t * 8.5 + 1.7) + 0.25 * sin(t * 17.0)
        return (18 + smooth(1.0 - t) * 96) * pulse + (fbm(t * 6.0, 9.3, 3, 63) - 0.5) * 30

    def branch_x(py, side, cx_main, w_main):
        """Микротрещины-ветви: растут прямо из кромки главной расщелины."""
        t = (py - FY0) / (FY1 - FY0)
        reach = (30 + sin(t * 5.0) * 18) * (1.0 - t * 1.4)  # короче к низу
        cx = cx_main + side * (w_main / 2 + 2 + max(reach, 6))
        cx += (fbm(t * 4.0 + side * 13.7, 2.9, 4, 67) - 0.5) * 40
        return cx

    def branch_alive(py):
        t = (py - FY0) / (FY1 - FY0)
        # ветви живут только в верхней половине
        return t < 0.42

    for y in range(H):
        py = float(y)
        # рваные границы проёма: крупная рвань + мелкая бахрома
        LX = FX0 + (fbm(py * 0.006, 1.1, 4, 5) - 0.5) * 150 + (fbm(py * 0.05, 2.2, 2, 6) - 0.5) * 26
        RX = FX1 + (fbm(py * 0.006, 3.3, 4, 7) - 0.5) * 150 + (fbm(py * 0.05, 4.4, 2, 8) - 0.5) * 26
        TY = FY0 + (fbm(0.7, py * 0.006, 4, 9) - 0.5) * 110 + (fbm(1.9, py * 0.05, 2, 10) - 0.5) * 22
        BY = FY1 + (fbm(3.1, py * 0.006, 4, 11) - 0.5) * 130

        cx_rift, t_rift = rift_x(py)
        rw = rift_w(t_rift)

        for x in range(W):
            px = float(x)

            # ---- комната / рама
            in_win = (px > LX and px < RX and py > TY and py < BY)

            # перекладина окна: грязно-серая, ловит вечер — отделена от неба тоном
            if in_win and abs(px - (MULLION + (fbm(py * 0.01, 6.6, 3, 13) - 0.5) * 24)) < 15:
                g = fbm(px * 0.05, py * 0.05, 3, 21)
                c = mix((96, 90, 96), (44, 42, 50), g)
                _put(img, x, y, c)
                continue

            if not in_win:
                edge = min(px - LX, RX - px, py - TY, BY - py)
                g = fbm(px * 0.04, py * 0.04, 4, 21)
                c = mix(INK, (18, 18, 26), g * 0.3)
                if edge < 20:
                    c = mix(c, (46, 44, 54), (1 - edge / 20) * 0.6)  # кромка ловит вечер
                rip = fbm(px * 0.006, py * 0.006, 5, 31)
                if rip < 0.42:
                    c = mix(c, INK, (0.42 - rip) * 4.0)
                _put(img, x, y, c)
                continue

            # ---- небо
            sy = (py - TY) / (BY - TY)
            if sy < 0.52:
                c = mix(SKY_TOP, SKY_MID, (sy / 0.52) ** 1.6)
            else:
                c = mix(SKY_MID, SKY_LOW, smooth((sy - 0.52) / 0.48) * 0.92)

            # редкая гравюрная штриховка неба (перистая, неровная)
            hh = sin((px * 0.55 + py * 0.83) * pi / 5.5 + fbm(px * 0.01, py * 0.01, 2, 44) * 6.0)
            if hh > 0.92 and sy > 0.08 and sy < 0.75:
                c = mix(c, (0, 0, 0), 0.12)
            # тусклые звёзды: редкие, мёртвые, гуще влево от расщелины
            st = hash2(int(px // 5), int(py // 5), 88)
            if st > 0.993 and sy < 0.5:
                glow = 0.35 + 0.3 * hash2(int(px), int(py), 89)
                c = mix(c, (150, 148, 168), glow)

            # ---- расщелина мироздания
            dxr = px - cx_rift
            in_rift = abs(dxr) < rw / 2 and py < TY + (BY - TY) * 0.52
            # ветви-микротрещины
            if not in_rift and branch_alive(py):
                for side in (-1, 1):
                    bx = branch_x(py, side, cx_rift, rw)
                    bw = 7 + (fbm(py * 0.02, 7.7, 2, 69) - 0.5) * 6
                    if abs(px - bx) < bw / 2:
                        in_rift = True
                        break
            if in_rift:
                # внутри — глухая чернота + редкие мёртвые точки
                c = (3, 3, 7)
                sp = hash2(int(px * 5) ^ 3, int(py * 5) ^ 5, 77)
                if sp > 0.9982:
                    c = (108, 106, 124)
            else:
                # кромка: штрих-филаменты, стягивающиеся к дыре
                dist = abs(dxr) - rw / 2
                if dist < 70 and py < TY + (BY - TY) * 0.62:
                    fall = 1.0 - dist / 70.0
                    ang = fbm(px * 0.03, py * 0.003, 2, 65)
                    fil = sin(px * 1.7 + ang * 20.0)
                    if fil > 0.25:
                        c = mix(c, (4, 4, 10), 0.45 * fall)
                # тёплая звезда-окно: город уходит на небо
                dsq = (px - 392) ** 2 + (py - 268) ** 2
                if dsq < 5:
                    c = mix(AMBER, (255, 214, 140), 0.5)
                elif dsq < 90:
                    c = mix(c, AMBER, 0.25 * (1 - dsq / 90))

            # ---- город: три плана
            if sy > 0.40:
                # фактор исчезновения: правый дрейф + близость к расщелине
                vx = clamp((px - (cx_rift - 250)) / 500.0, 0, 1)
                drift = clamp(vx * 1.15 - 0.28, 0, 1)
                hole = 0.0
                if py < TY + (BY - TY) * 0.72:
                    hole = clamp(1.0 - (abs(px - cx_rift) - rw / 2) / 300.0, 0, 1)
                vanish = max(drift, hole * 1.2)

                top_f = city_top_at(px, far)
                if top_f >= 0 and py > top_f:
                    # дальний рассыпается сильнее всех
                    keepf = 1.0
                    if vanish > 0.15:
                        u = fbm(px * 0.01, py * 0.045, 3, 91)
                        if u < (vanish - 0.15) * 0.9:
                            keepf = 0.0
                    if keepf:
                        c = mix(c, FAR_C, 0.95)
                        # редкие тусклые огни дальнего плана — жизнь ещё теплится
                        if hash2(int(px // 9), int(py // 9), 66) > 0.988:
                            c = mix(c, (120, 96, 66), 0.5)

                top_m = city_top_at(px, mid)
                if top_m >= 0 and py > top_m:
                    keepm = 1.0
                    if vanish > 0.30:
                        u = fbm(px * 0.012, py * 0.05, 3, 92)
                        if u < (vanish - 0.30) * 1.1:
                            keepm = 0.0
                    if keepm:
                        c = mix(c, MID_C, 0.94)

                top_n = city_top_at(px, near)
                if top_n >= 0 and py > top_n:
                    keepn = 1.0
                    if vanish > 0.55:
                        u = fbm(px * 0.014, py * 0.06, 3, 93)
                        if u < (vanish - 0.55) * 1.3:
                            keepn = 0.0
                    if keepn:
                        c = mix(c, NEAR_C, 0.97)
                        # окна ближнего плана: крупная сетка, своя фаза по дому
                        for (x0, x1, h, kind, aux) in near:
                            if x0 <= px <= x1:
                                gx = int((px - x0) // 26)
                                gy = int(py // 34)
                                wx = (px - x0) - gx * 26
                                wy = py - gy * 34
                                lit = hash2(gx + int(x0), gy, 55)
                                # у расщелины окна гаснут — город истончается
                                lit_thr = 0.55 + clamp(hole, 0, 1) * 0.45
                                if 7 < wx < 20 and 9 < wy < 26 and lit > lit_thr:
                                    flick = fbm(px * 0.08, py * 0.08, 2, 12)
                                    c = mix(c, AMBER, 0.6 + flick * 0.25)
                                break

            # ---- рваный туман у горизонта
            if sy > 0.55:
                band = fbm(px * 0.003, py * 0.045, 4, 71)
                if band > 0.58:
                    c = mix(c, FOG, (band - 0.58) * 1.4 * clamp((sy - 0.55) / 0.3, 0, 1))

            _put(img, x, y, c)

    return img


# матрица Байера 8x8 — упорядоченный дизеринг, детерминированный и
# хорошо сжимающийся (периодический корректируется фильтрами PNG)
BAYER = [
    [0, 32, 8, 40, 2, 34, 10, 42], [48, 16, 56, 24, 50, 18, 58, 26],
    [12, 44, 4, 36, 14, 46, 6, 38], [60, 28, 52, 20, 62, 30, 54, 22],
    [3, 35, 11, 43, 1, 33, 9, 41], [51, 19, 59, 27, 49, 17, 57, 25],
    [15, 47, 7, 39, 13, 45, 5, 37], [63, 31, 55, 23, 61, 29, 53, 21],
]
GRAIN = 9.0  # амплитуда зерна


def _put(img, x, y, c):
    g = (BAYER[y & 7][x & 7] / 64.0 - 0.5) * GRAIN
    i = (y * W + x) * 3
    img[i] = int(clamp(c[0] + g, 0, 255))
    img[i + 1] = int(clamp(c[1] + g, 0, 255))
    img[i + 2] = int(clamp(c[2] + g, 0, 255))


# ---------------------------------------------------------------- png


def write_png(path, img):
    raw = bytearray()
    stride = W * 3
    prev = bytearray(stride)

    def paeth(a, b, cc):
        p = a + b - cc
        pa, pb, pc = abs(p - a), abs(p - b), abs(p - cc)
        if pa <= pb and pa <= pc:
            return a
        if pb <= pc:
            return b
        return cc

    for y in range(H):
        row = img[y * stride:(y + 1) * stride]
        best = None
        best_sum = None
        for f in (0, 1, 2, 3, 4):
            out = bytearray(stride)
            s = 0
            for x in range(stride):
                a = row[x - 3] if x >= 3 else 0
                b = prev[x]
                cc = prev[x - 3] if x >= 3 else 0
                v = row[x]
                if f == 1:
                    d = (v - a) & 0xFF
                elif f == 2:
                    d = (v - b) & 0xFF
                elif f == 3:
                    d = (v - ((a + b) >> 1)) & 0xFF
                elif f == 4:
                    d = (v - paeth(a, b, cc)) & 0xFF
                else:
                    d = v
                out[x] = d
                s += d if d < 128 else 256 - d
            if best_sum is None or s < best_sum:
                best_sum = s
                best = (f, out)
        f, out = best
        raw.append(f)
        raw += out
        prev = row

    comp = zlib.compress(bytes(raw), 9)

    def chunk(tag, data):
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n"
    png += chunk(b"IHDR", struct.pack(">IIBBBBB", W, H, 8, 2, 0, 0, 0))
    png += chunk(b"IDAT", comp)
    png += chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)


if __name__ == "__main__":
    os.makedirs("output", exist_ok=True)
    data = render()
    write_png(os.path.join("output", "entry.png"), data)
    print("done", W, H)
