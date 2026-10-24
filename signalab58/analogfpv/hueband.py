"""Slow per-line hue / saturation errors (hue bands). Pure functions of (line, time): no state needed."""
import numpy as np

LINE_RATE = 15734.264


def _vnoise(x: np.ndarray, seed: int, salt: int) -> np.ndarray:
    """Smooth deterministic noise in -1..1, one random value per integer x."""
    k = np.floor(x).astype(np.int64)
    f = x - k
    ks = np.unique(np.concatenate([k, k + 1]))
    vals = {int(kk): np.random.default_rng([abs(int(seed)), salt, int(kk) + 1_000_000]).uniform(-1, 1) for kk in ks}
    a = np.array([vals[int(kk)] for kk in k])
    b = np.array([vals[int(kk) + 1] for kk in k])
    s = 0.5 - 0.5 * np.cos(np.pi * f)
    return a + (b - a) * s


def _shape(x: np.ndarray, tri: float) -> np.ndarray:
    s = np.sin(x)
    return (1.0 - tri) * s + tri * (2.0 / np.pi) * np.arcsin(s)


def _wave(l, t, p, extra=0.0):
    tri = p["hb_shape"]
    x1 = 2 * np.pi * (l / p["hb_period_lines"] + p["hb_drift_hz"] * t) + extra
    w = _shape(x1, tri)
    lvl = p["hb_second_level"]
    if lvl > 0:
        x2 = 2 * np.pi * (l / (p["hb_period_lines"] * p["hb_second_ratio"]) + p["hb_drift_hz"] * 0.37 * t) + extra
        w = (w + lvl * _shape(x2, 1.0 - tri)) / (1.0 + lvl)
    return w


def hue_sat_lines(n_lines: int, t: float, p: dict):
    """Returns (hue rotation in radians, saturation gain) for each line of one field at time t (s)."""
    l = np.arange(n_lines, dtype=np.float64)
    hue = np.deg2rad(p["hb_hue_deg"]) * _wave(l, t, p)
    if p["hb_wander_deg"] > 0:
        x = l / p["hb_wander_lines"] + t / max(p["hb_wander_time_s"], 1e-3)
        hue = hue + np.deg2rad(p["hb_wander_deg"]) * _vnoise(x, p["seed"], 1)
    gain = 1.0 + p["hb_sat_amp"] * _wave(l, t, p, extra=np.pi / 2)
    if p["hb_env_s"] > 0:
        n = 0.5 + 0.5 * _vnoise(np.array([t / p["hb_env_s"]]), p["seed"], 2)[0]
        e = float(np.clip((n - 0.25) / 0.5, 0.0, 1.0))
        e = e * e * (3 - 2 * e)
        hue = hue * e
        gain = 1.0 + (gain - 1.0) * e
    return hue, np.clip(gain, 0.0, 4.0)
