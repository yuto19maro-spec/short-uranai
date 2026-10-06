#!/usr/bin/env python3
"""海の背景動画をプログラムで生成する (素材サイトから落とせない時の代替)。

    python3 make_sea_bg.py            # bg/ に全種類を書き出す
    python3 make_sea_bg.py moon sunset

種類: moon(月夜の海) / sunset(夕焼けの海) / rays(海中の光芒) / surface(海中から見上げた水面) / deep(深海と泡)
"""
import os
import subprocess
import sys

import numpy as np

ROOT = os.path.dirname(os.path.abspath(__file__))
RW, RH = 540, 960      # 内部解像度 (書き出し時に 1080x1920 へ拡大)
FPS, DUR = 30, float(os.environ.get("SEA_DUR", 7.0))


def writer(name):
    out = os.path.join(ROOT, "bg", f"sea_{name}.mp4")
    os.makedirs(os.path.dirname(out), exist_ok=True)
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-y", "-f", "rawvideo", "-pix_fmt", "rgb24",
                          "-s", f"{RW}x{RH}", "-r", str(FPS), "-i", "-",
                          "-vf", "scale=1080:1920:flags=lanczos,noise=alls=4:allf=t",
                          "-c:v", "libx264", "-crf", "18", "-preset", "medium", "-pix_fmt", "yuv420p", out],
                         stdin=subprocess.PIPE)
    return p, out


def to8(img):
    return (np.clip(img, 0, 1) ** (1 / 2.2) * 255).astype(np.uint8)


def smoothstep(a, b, x):
    t = np.clip((x - a) / (b - a), 0, 1)
    return t * t * (3 - 2 * t)


# ------------------------------------------------------------------ 海面 (月夜/夕焼け)
WAVES = [  # (波長m, 振幅m, 方向deg, 位相)
    (9.0, 0.22, 8, 0.0), (6.3, 0.16, -22, 1.3), (4.1, 0.10, 35, 2.1), (2.7, 0.07, -48, 0.4),
    (1.9, 0.045, 14, 3.3), (1.3, 0.03, -65, 5.1), (0.85, 0.018, 52, 0.9), (0.6, 0.012, -5, 2.6),
    (0.42, 0.008, 28, 4.4), (0.3, 0.0055, -38, 1.7), (0.21, 0.0038, 71, 3.9),
]


def ocean(name, sky_top, sky_hor, water_deep, light_dir, light_col, light_size, light_glow,
          hor=0.40, cam_h=2.2, stars=False, spec_pow=900.0, haze_col=None):
    rng = np.random.default_rng(3)
    p, out = writer(name)
    yy, xx = np.mgrid[0:RH, 0:RW].astype(np.float32)
    f = RW * 1.25
    hy = RH * hor
    dx = (xx - RW / 2) / f
    dy = -(yy - hy) / f
    dz = np.ones_like(dx)
    n = np.sqrt(dx * dx + dy * dy + dz * dz)
    dx, dy, dz = dx / n, dy / n, dz / n
    L = np.array(light_dir, np.float32)
    L /= np.linalg.norm(L)

    # 空
    t = np.clip(dy / 0.75, 0, 1)
    sky = sky_hor[None, None, :] * (1 - t[..., None]) ** 1 + sky_top[None, None, :] * t[..., None]
    cosl = dx * L[0] + dy * L[1] + dz * L[2]
    disc = smoothstep(1 - light_size * 1.15, 1 - light_size, cosl)
    halo = np.clip((cosl - 0.80) / 0.20, 0, 1) ** 14 * light_glow
    sky = sky + light_col[None, None, :] * (disc[..., None] * 3.0 + halo[..., None])
    if stars:
        sm = (rng.random((RH, RW)) > 0.9985) & (dy > 0.05)
        star_amp = rng.random((RH, RW)) * sm
    sea = dy < -0.0005
    ty = -cam_h / np.where(sea, dy, -1)
    X, Z = dx * ty, dz * ty
    fade_all = np.exp(-Z / 140.0)

    for fi in range(int(DUR * FPS)):
        tm = fi / FPS
        gx = np.zeros_like(X)
        gz = np.zeros_like(X)
        for lam, amp, deg, ph in WAVES:
            k = 2 * np.pi / lam
            w = np.sqrt(9.81 * k)
            a = np.radians(deg)
            kx, kz = k * np.sin(a), k * np.cos(a)
            # 遠方では細かい波を弱めてチラつきを防ぐ
            atten = np.exp(-Z * k / 60.0)
            c = np.cos(kx * X + kz * Z - w * tm + ph) * amp * atten
            gx += c * kx
            gz += c * kz
        nx, ny, nz = -gx, np.ones_like(gx), -gz
        nn = np.sqrt(nx * nx + ny * ny + nz * nz)
        nx, ny, nz = nx / nn, ny / nn, nz / nn
        dn = dx * nx + dy * ny + dz * nz
        rx, ry, rz = dx - 2 * dn * nx, dy - 2 * dn * ny, dz - 2 * dn * nz
        ry = np.abs(ry)
        rt = np.clip(ry / 0.75, 0, 1)
        refl = sky_hor[None, None, :] * (1 - rt[..., None]) + sky_top[None, None, :] * rt[..., None]
        spec = np.clip(rx * L[0] + ry * L[1] + rz * L[2], 0, 1) ** spec_pow * 9.0
        fres = 0.02 + 0.98 * (1 - np.clip(-dn, 0, 1)) ** 5
        water = water_deep[None, None, :] * (1 - fres[..., None]) + refl * fres[..., None]
        water = water + light_col[None, None, :] * spec[..., None]
        hz = haze_col if haze_col is not None else sky_hor
        water = water * fade_all[..., None] + hz[None, None, :] * (1 - fade_all[..., None]) * 0.9
        img = np.where(sea[..., None], water, sky)
        if stars:
            tw = 0.6 + 0.4 * np.sin(tm * 3 + xx * 0.7)
            img = img + (star_amp * tw)[..., None] * 0.6
        # ビネット
        v = 1 - 0.45 * (((xx - RW / 2) / RW) ** 2 + ((yy - RH / 2) / RH) ** 2) * 2
        img = img * v[..., None]
        p.stdin.write(to8(img).tobytes())
        if fi % 30 == 0:
            print(f"\r{name} {tm:.1f}s", end="", flush=True)
    p.stdin.close()
    p.wait()
    print("\r wrote", out)


def moon():
    ocean("moon", sky_top=np.array([0.004, 0.008, 0.025]), sky_hor=np.array([0.03, 0.05, 0.10]),
          water_deep=np.array([0.002, 0.008, 0.02]), light_dir=(0.10, 0.20, 1.0),
          light_col=np.array([0.95, 0.95, 1.0]), light_size=0.0006, light_glow=0.08, hor=0.42,
          stars=True, spec_pow=700.0)


def sunset():
    ocean("sunset", sky_top=np.array([0.10, 0.04, 0.10]), sky_hor=np.array([0.95, 0.38, 0.10]),
          water_deep=np.array([0.01, 0.02, 0.04]), light_dir=(0.0, 0.035, 1.0),
          light_col=np.array([1.0, 0.62, 0.25]), light_size=0.0016, light_glow=1.4, hor=0.45,
          spec_pow=260.0, haze_col=np.array([0.85, 0.35, 0.12]))


# ------------------------------------------------------------------ 海中
def _noise1d(rng, n=4096):
    """周期的な1Dノイズテーブル"""
    v = rng.random(n)
    for _ in range(12):
        v = (v + np.roll(v, 1) + np.roll(v, -1)) / 3
    return (v - v.min()) / (v.max() - v.min())


def underwater(name, top, bottom, ray_amt, particles, bubbles, surface_band):
    rng = np.random.default_rng(11)
    p, out = writer(name)
    yy, xx = np.mgrid[0:RH, 0:RW].astype(np.float32)
    t = yy / RH
    base = top[None, None, :] * (1 - t[..., None]) ** 1.3 + bottom[None, None, :] * (1 - (1 - t[..., None]) ** 1.3)
    sx, sy = RW * 0.55, -RH * 0.35
    ang = np.arctan2(xx - sx, yy - sy)
    dist = np.sqrt((xx - sx) ** 2 + (yy - sy) ** 2)
    nt = _noise1d(rng)
    nt2 = _noise1d(rng)
    pp = rng.random((particles, 4))
    bb = rng.random((bubbles, 4))
    for fi in range(int(DUR * FPS)):
        tm = fi / FPS
        u = (ang * 260 + tm * 9) % 4096
        u2 = (ang * 520 - tm * 14) % 4096
        rays = nt[u.astype(int) % 4096] ** 3 * 0.7 + nt2[u2.astype(int) % 4096] ** 4 * 0.6
        rays = rays * np.exp(-dist / (RH * 0.9)) * ray_amt
        img = base + np.array([0.35, 0.65, 0.85])[None, None, :] * rays[..., None]
        if surface_band:
            s = np.clip(1 - yy / (RH * 0.18), 0, 1) ** 2
            rip = (np.sin(xx * 0.045 + tm * 1.7 + np.sin(yy * 0.08 + tm) * 2) *
                   np.sin(xx * 0.021 - tm * 1.1 + yy * 0.03)) * 0.5 + 0.5
            img = img + np.array([0.5, 0.8, 0.95])[None, None, :] * (s * rip ** 3 * 0.9)[..., None]
        # 浮遊物
        for x0, y0, sz, sp in pp:
            px = (x0 * RW + np.sin(tm * 0.6 + sp * 9) * 10) % RW
            py = (y0 * RH - tm * (4 + sp * 10)) % RH
            r = 0.6 + sz * 1.6
            ix, iy = int(px), int(py)
            if 2 <= ix < RW - 3 and 2 <= iy < RH - 3:
                img[iy - 1:iy + 2, ix - 1:ix + 2] += 0.08 * r
        # 泡
        for x0, y0, sz, sp in bb:
            r = 2 + sz * 7
            py = (y0 * RH - tm * (40 + sp * 80)) % (RH + 40) - 20
            px = x0 * RW + np.sin(tm * 3 + sp * 20) * 4
            x1, x2 = int(max(0, px - r - 2)), int(min(RW, px + r + 3))
            y1, y2 = int(max(0, py - r - 2)), int(min(RH, py + r + 3))
            if x2 <= x1 or y2 <= y1:
                continue
            d = np.sqrt((xx[y1:y2, x1:x2] - px) ** 2 + (yy[y1:y2, x1:x2] - py) ** 2)
            ring = np.exp(-((d - r) ** 2) / 1.2) * 0.55 + np.exp(-((xx[y1:y2, x1:x2] - px + r * 0.35) ** 2 +
                                                                (yy[y1:y2, x1:x2] - py + r * 0.35) ** 2) / 2.0) * 0.6
            img[y1:y2, x1:x2] += np.array([0.7, 0.9, 1.0])[None, None, :] * ring[..., None]
        v = 1 - 0.5 * (((xx - RW / 2) / RW) ** 2 + ((yy - RH / 2) / RH) ** 2) * 2
        img = img * v[..., None]
        p.stdin.write(to8(img).tobytes())
        if fi % 30 == 0:
            print(f"\r{name} {tm:.1f}s", end="", flush=True)
    p.stdin.close()
    p.wait()
    print("\r wrote", out)


def rays():
    underwater("rays", top=np.array([0.05, 0.30, 0.45]), bottom=np.array([0.0, 0.015, 0.05]),
               ray_amt=0.55, particles=260, bubbles=6, surface_band=True)


def deep():
    underwater("deep", top=np.array([0.01, 0.07, 0.14]), bottom=np.array([0.0, 0.003, 0.012]),
               ray_amt=0.22, particles=380, bubbles=26, surface_band=False)


def surface():
    """海中から水面を見上げた映像 (スネルの窓 + 揺らぐ光)"""
    p, out = writer("surface")
    yy, xx = np.mgrid[0:RH, 0:RW].astype(np.float32)
    X = (xx - RW / 2) / RW * 6
    Y = (yy - RH * 0.15) / RH * 10
    for fi in range(int(DUR * FPS)):
        tm = fi / FPS
        gx = np.zeros_like(X)
        gy = np.zeros_like(X)
        for lam, amp, deg, ph in WAVES[2:]:
            k = 2 * np.pi / lam
            w = np.sqrt(9.81 * k) * 0.5
            a = np.radians(deg * 2.3)
            kx, ky = k * np.sin(a), k * np.cos(a)
            c = np.cos(kx * X + ky * Y - w * tm + ph) * amp
            gx += c * kx
            gy += c * ky
        win = np.exp(-((X + gx * 0.8) ** 2 * 0.22 + (Y + gy * 0.8 - 0.4) ** 2 * 0.10))
        caus = np.clip(1 - np.sqrt(gx * gx + gy * gy) * 1.4, 0, 1) ** 6
        depth = np.clip(yy / RH, 0, 1)
        img = (np.array([0.02, 0.10, 0.20])[None, None, :] * (1 - depth[..., None]) +
               np.array([0.0, 0.01, 0.03])[None, None, :] * depth[..., None])
        img = img + np.array([0.55, 0.85, 1.0])[None, None, :] * (win * (0.35 + caus * 1.1))[..., None]
        v = 1 - 0.5 * (((xx - RW / 2) / RW) ** 2 + ((yy - RH / 2) / RH) ** 2) * 2
        img = img * v[..., None]
        p.stdin.write(to8(img).tobytes())
        if fi % 30 == 0:
            print(f"\rsurface {tm:.1f}s", end="", flush=True)
    p.stdin.close()
    p.wait()
    print("\r wrote", out)


ALL = {"moon": moon, "sunset": sunset, "rays": rays, "surface": surface, "deep": deep}

if __name__ == "__main__":
    for k in (sys.argv[1:] or ALL):
        ALL[k]()
