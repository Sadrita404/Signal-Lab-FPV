"""NTSC composite video: constants, field encoder, field decoder.

The signal is a 1-D array sampled at 4x the color subcarrier (14.318 MHz),
so one line = 910 samples and the subcarrier phase advances exactly 90 degrees
per sample. Levels are in IRE (blanking 0, sync tip -40, white 100).

A "field" is 262 lines (parity 0) or 263 lines (parity 1); together they make
the 525-line frame. Each field carries its own vertical-blanking interval
(equalizing pulses, serrated vertical sync) and 240 active picture lines.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

import cv2
import numpy as np
from scipy.ndimage import convolve1d
from scipy.signal import firwin, lfilter, oaconvolve

FSC = 315e6 / 88.0            # 3.579545 MHz color subcarrier
FS = 4.0 * FSC                # 14.318181 MHz sample rate
SPL = 910                     # samples per line
BURST_START = 78              # burst begins here (samples); width and cycles are parameters
ACTIVE_START, ACTIVE_LEN = 134, 754  # 52.6 us of picture per line
LINES = (262, 263)            # lines in field parity 0 / 1
ACTIVE_LINE0, ACTIVE_LINES = 21, 240
BURST_FIRST_LINE = 9          # no burst during the vertical sync interval
FIELD_RATE = 60000.0 / 1001.0
RASTER_W, RASTER_H = 640, 480

_K = np.arange(4)
_THETA = np.deg2rad(33.0)
COS4 = np.cos(_THETA + np.pi / 2 * _K).astype(np.float32)   # I carrier by (sample index % 4)
SIN4 = np.sin(_THETA + np.pi / 2 * _K).astype(np.float32)   # Q carrier
BURST4 = np.array([0, -1, 0, 1], np.float32)                 # -sin(wt): burst at 180 deg
SIN0 = np.array([0, 1, 0, -1], np.float32)                   # plain sin / cos of the nominal carrier,
COS0 = np.array([1, 0, -1, 0], np.float32)                   # used to measure the burst phase

RGB2YIQ = np.array([[0.299, 0.587, 0.114],
                    [0.5959, -0.2746, -0.3213],
                    [0.2115, -0.5227, 0.3112]], np.float32)
YIQ2RGB = np.linalg.inv(RGB2YIQ).astype(np.float32)


@dataclass
class FieldCtx:
    """Where a field sits in the continuous signal."""
    index: int      # field number since start
    parity: int     # 0 or 1
    n_lines: int    # 262 or 263
    offset: int     # global index of this field's first sample


# --------------------------------------------------------------------- filters
def _odd(n: int) -> int:
    return int(n) | 1


@lru_cache(maxsize=64)
def _lowpass(cut_mhz: float, ntaps: int = 63) -> np.ndarray:
    return firwin(_odd(ntaps), cut_mhz * 1e6, fs=FS).astype(np.float32)


@lru_cache(maxsize=16)
def _chroma_bandpass(lo_mhz: float, hi_mhz: float, ntaps: int = 63) -> np.ndarray:
    return firwin(_odd(ntaps), [lo_mhz * 1e6, hi_mhz * 1e6], pass_zero=False, fs=FS).astype(np.float32)


def _lp_rows(x: np.ndarray, cut_mhz: float, ntaps: int = 63) -> np.ndarray:
    return convolve1d(x, _lowpass(round(cut_mhz, 4), ntaps), axis=1, mode="nearest")


def _fir_flat(x: np.ndarray, taps: np.ndarray) -> np.ndarray:
    """Zero-phase FIR on a long 1-D signal (FFT based)."""
    return oaconvolve(x, taps, mode="same").astype(np.float32)


# --------------------------------------------------------------------- sync
@lru_cache(maxsize=8)
def _sync_template(n_lines: int, hsync_len: int, sync_ire: float) -> np.ndarray:
    sig = np.zeros((n_lines, SPL), np.float32)
    half = SPL // 2
    eq = hsync_len // 2                    # equalizing pulses are half-width
    for ln in range(n_lines):
        if ln < 3 or 6 <= ln < 9:          # equalizing pulses: 2 narrow pulses per line
            sig[ln, 0:eq] = sync_ire
            sig[ln, half:half + eq] = sync_ire
        elif 3 <= ln < 6:                  # vertical sync: broad pulses with serrations
            sig[ln, 0:half - hsync_len] = sync_ire
            sig[ln, half:SPL - hsync_len] = sync_ire
        else:                              # normal horizontal sync
            sig[ln, 0:hsync_len] = sync_ire
    return sig


# --------------------------------------------------------------------- encode
def prepare_field_rgb(rgb: np.ndarray) -> np.ndarray:
    """(240, W, 3) float RGB in 0..1 -> (240, ACTIVE_LEN, 3) resampled to the line's active window."""
    interp = cv2.INTER_AREA if rgb.shape[1] > ACTIVE_LEN else cv2.INTER_LINEAR
    return cv2.resize(rgb, (ACTIVE_LEN, rgb.shape[0]), interpolation=interp)


def encode_field(rgb: np.ndarray, ctx: FieldCtx, p: dict) -> np.ndarray:
    """RGB field (240, W, 3) in 0..1 -> composite signal (n_lines, SPL) in IRE."""
    act = prepare_field_rgb(rgb.astype(np.float32))
    yiq = act @ RGB2YIQ.T
    taps = p["filter_taps"]
    y = _lp_rows(yiq[..., 0], p["luma_bw_mhz"], taps)
    i = _lp_rows(yiq[..., 1], p["i_bw_mhz"], taps)
    q = _lp_rows(yiq[..., 2], p["q_bw_mhz"], taps)

    setup = p["black_setup_ire"]
    scale = 100.0 - setup
    cols = np.arange(ACTIVE_START, ACTIVE_START + ACTIVE_LEN)
    lines = np.arange(ACTIVE_LINE0, ACTIVE_LINE0 + ACTIVE_LINES)
    k = (ctx.offset + lines[:, None] * SPL + cols[None, :]) % 4
    video = setup + scale * (y + i * COS4[k] + q * SIN4[k])

    sig = _sync_template(ctx.n_lines, p["hsync_len"], p["sync_level_ire"]).copy()
    burst_len = 4 * p["burst_cycles"]
    bl = np.arange(BURST_FIRST_LINE, ctx.n_lines)
    bc = np.arange(BURST_START, BURST_START + burst_len)
    kb = (ctx.offset + bl[:, None] * SPL + bc[None, :]) % 4
    sig[BURST_FIRST_LINE:, BURST_START:BURST_START + burst_len] = p["burst_amp_ire"] * BURST4[kb]
    sig[ACTIVE_LINE0:ACTIVE_LINE0 + ACTIVE_LINES, ACTIVE_START:ACTIVE_START + ACTIVE_LEN] = video
    return np.clip(sig, p["sync_level_ire"], p["composite_clip_ire"])


# --------------------------------------------------------------------- decode
def _burst_phasors(chroma: np.ndarray, ctx: FieldCtx, p: dict) -> np.ndarray:
    """Per-line complex burst measurement A*exp(j*phase error); the middle of the burst is used."""
    length = 4 * p["burst_cycles"]
    g0, g1 = int(0.2 * length), int(0.8 * length)
    lines = np.arange(BURST_FIRST_LINE, ctx.n_lines)
    cols = np.arange(BURST_START + g0, BURST_START + g1)
    seg = chroma.reshape(ctx.n_lines, SPL)[BURST_FIRST_LINE:, BURST_START + g0:BURST_START + g1]
    k = (ctx.offset + lines[:, None] * SPL + cols[None, :]) % 4
    s = 2.0 * np.mean(seg * SIN0[k], axis=1)
    c = 2.0 * np.mean(seg * COS0[k], axis=1)
    return (-s) + 1j * (-c)            # the ideal burst is -sin(wt), so this is +A at zero phase error


def _color_lock(chroma: np.ndarray, ctx: FieldCtx, p: dict, state: dict | None):
    """The goggles' color reference: per active line, (hue rotation in radians, chroma gain).

    A crystal oscillator (VCXO) is steered by a phase-locked loop that compares it with each line's burst.
    The loop has momentum: a burst knocked by noise or interference pushes the reference off, and it swings
    back over tens of lines (hue bands that fade out down the picture). With no burst during vertical sync
    the oscillator free-runs on its own small frequency error. Automatic color gain (ACC) scales chroma by
    how big the burst looks, so the same hit also changes saturation. The color killer checks, once per
    field, how much of the burst lines up with the reference; if too little, the next field is shown gray.
    """
    n = ctx.n_lines
    act = slice(ACTIVE_LINE0, ACTIVE_LINE0 + ACTIVE_LINES)
    phi, gain = np.zeros(n), np.ones(n)
    a_nom = p["burst_amp_ire"]
    if not p["burst_lock"] or a_nom <= 0:
        return phi + np.deg2rad(p["hue_offset_deg"]), gain
    st = state if state is not None else {}
    burst = np.zeros(n, np.complex128)
    burst[BURST_FIRST_LINE:] = _burst_phasors(chroma, ctx, p)

    wn = 2.0 * np.pi / p["burst_lock_lines"]                # loop natural frequency, rad per line
    kp, ki = 2.0 * p["pll_damping"] * wn, wn * wn
    drift = 2.0 * np.pi * p["pll_drift_hz"] / (FS / SPL)    # oscillator's own error, rad per line
    th, w = st.get("pll", (0.0, -drift))                    # start locked
    k_acc = np.exp(-1.0 / p["acc_lines"])
    amp, killed = st.get("acc", (a_nom, False))
    ip_sum = 0.0
    g_max, kill_on = p["acc_max_gain"], p["killer_level"]
    for i in range(n):
        if i >= BURST_FIRST_LINE:
            v = burst[i] * np.exp(-1j * th)                 # burst seen against the current reference
            e = float(np.clip(v.imag / a_nom, -1.0, 1.0))   # multiplier phase detector, saturates
            w += ki * e
            th += drift + w + kp * e
            amp = k_acc * amp + (1.0 - k_acc) * abs(burst[i])
            ip_sum += v.real                                # in-phase part: drops when lock is lost
        else:
            th += drift + w                                 # vertical sync: no burst, free-running
        phi[i] = th
        gain[i] = 0.0 if killed else min(a_nom / max(amp, 1e-6), g_max)
    st["pll"] = (float(np.mod(th + np.pi, 2.0 * np.pi) - np.pi), float(w))
    q = ip_sum / (n - BURST_FIRST_LINE) / a_nom              # field's lock quality, 1 = perfect
    st["lock_q"] = q
    if p["color_killer"]:                                     # decided for the next field, with hysteresis
        killed = q < kill_on if not killed else q < kill_on + 0.15
    st["acc"] = (float(amp), bool(killed))
    return phi + np.deg2rad(p["hue_offset_deg"]), gain


@lru_cache(maxsize=16)
def _edge_delay(hsync_len: int, sync_ire: float, thr: float) -> float:
    """Where the sync separator places a perfect pulse's edge (filter delay), so a clean signal shifts by 0."""
    line = np.zeros(4 * SPL, np.float32)
    line[2 * SPL:2 * SPL + hsync_len] = sync_ire
    s = _fir_flat(line, _lowpass(1.5, 31))
    e = int(np.argmax(s < thr))
    return float(e - 1 + (s[e - 1] - thr) / (s[e - 1] - s[e]) - 2 * SPL)


def _sync_recover(flat: np.ndarray, ctx: FieldCtx, p: dict, state: dict | None):
    """The goggles' sync separator and line/field oscillators -> (source line, horizontal shift) per output row.

    The sync separator low-passes the signal and slices it at `sync_slice_ire`; a pulse counts when it stays
    below for at least half a sync width. The horizontal oscillator runs a little off (`hsync_drift` samples
    per line) and every pulse it finds pulls it back (1/`hsync_lock_lines` of the error per line). When pulses
    are missing (static, dips) it coasts and the lines slide sideways more and more, then snap back over a
    few lines once pulses return. Noise that dips below the slice level makes it fire early: torn lines.
    The vertical oscillator looks for the broad vertical-sync pulses once per field; if it can't find them
    it free-runs and the picture rolls by `vsync_drift_lines` per field, pulling back in when they return.
    """
    n = ctx.n_lines
    rows = np.arange(ACTIVE_LINE0, ACTIVE_LINE0 + ACTIVE_LINES)
    if not p["sync_enable"]:
        return rows, np.zeros(ACTIVE_LINES)
    st = state if state is not None else {}
    s = _fir_flat(flat, _lowpass(1.5, 31))
    thr = p["sync_slice_ire"]
    below = s < thr
    L = max(4, p["hsync_len"] // 2)
    csum = np.concatenate([[0], np.cumsum(below)])
    run = np.zeros(below.size, np.int64)
    run[:below.size - L + 1] = csum[L:] - csum[:-L]               # samples below the slice in the next L
    edge = below & ~np.concatenate([[False], below[:-1]]) & (run >= 0.8 * L)
    edges = np.flatnonzero(edge).astype(np.float64)
    if edges.size:                                                # sub-sample position of each falling edge
        e = edges.astype(np.int64)
        a, b = s[np.maximum(e - 1, 0)], s[e]
        edges = edges - 1 + np.clip((a - thr) / np.maximum(a - b, 1e-6), 0.0, 1.0)

    kp = 1.0 / p["hsync_lock_lines"]
    drift = p["hsync_drift"]
    off0 = drift * (1.0 - kp) / kp + _edge_delay(p["hsync_len"], p["sync_level_ire"], thr)   # where it sits when locked
    pos = st.get("h_pos", off0)
    win = 120.0                                                   # pull-in range, samples
    xs = np.empty(n)
    for ln in range(n):
        pos += drift                                              # free-running oscillator
        x0 = ln * SPL
        j = np.searchsorted(edges, x0 + pos)
        best = None
        for c in (j - 1, j):
            if 0 <= c < edges.size and abs(edges[c] - x0 - pos) < win and (best is None or abs(edges[c] - x0 - pos) < abs(best - x0 - pos)):
                best = edges[c]
        if best is not None:
            pos += kp * (best - x0 - pos)                         # pulse found: pull toward it
        pos = (pos + SPL / 2) % SPL - SPL / 2                     # a far-off oscillator catches the next line
        xs[ln] = pos - off0
    st["h_pos"] = float(pos)

    vs = below.reshape(n, SPL).mean(axis=1) > 0.6                 # broad vertical-sync pulses in this line
    v = st.get("v_off", 0.0)
    if vs[2:8].any():
        v *= 1.0 - p["vsync_lock"]
        v = 0.0 if abs(v) < 0.5 else v
    else:
        v += p["vsync_drift_lines"]
    v = (v + n / 2) % n - n / 2
    st["v_off"] = float(v)
    src = (rows + int(round(v))) % n
    return src, xs[src]


def decode_field(sig: np.ndarray, ctx: FieldCtx, p: dict, state: dict | None = None) -> np.ndarray:
    """Composite signal (n_lines, SPL) -> RGB field (240, 640, 3) in 0..1."""
    flat = sig.reshape(-1).astype(np.float32)
    if p["rx_clip_enable"]:                            # goggle video input range: color is cut along with the peaks
        flat = np.clip(flat, p["rx_clip_low_ire"], p["rx_clip_high_ire"])

    # --- luma / chroma separation: blend of notch and comb
    taps = p["filter_taps"]
    bp = _chroma_bandpass(round(p["chroma_bp_low_mhz"], 4), round(p["chroma_bp_high_mhz"], 4), taps)
    chroma_notch = _fir_flat(flat, bp)
    a = p["comb_amount"]
    if a > 0:
        z = np.zeros(SPL, np.float32)
        prev = np.concatenate([z, flat[:-SPL]])
        nxt = np.concatenate([flat[SPL:], z])
        chroma_comb = _fir_flat(0.5 * flat - 0.25 * (prev + nxt), bp)
        chroma = (1 - a) * chroma_notch + a * chroma_comb
    else:
        chroma = chroma_notch
    luma = flat - chroma

    # --- chroma demodulation (ideal reference; burst lock arrives with the sync step)
    k = (ctx.offset + np.arange(flat.size)) % 4
    lp = _lowpass(round(p["dec_chroma_bw_mhz"], 4), taps)
    i_dem = _fir_flat(2.0 * chroma * COS4[k], lp)
    q_dem = _fir_flat(2.0 * chroma * SIN4[k], lp)

    # --- sync recovery: which line each output row shows, and how far it is shifted sideways
    src, dx = _sync_recover(flat, ctx, p, state)
    pos = (src * SPL + ACTIVE_START)[:, None] + np.arange(ACTIVE_LEN)[None, :] + dx[:, None]
    i0 = np.clip(np.floor(pos).astype(np.int64), 0, flat.size - 2)
    fr = (pos - np.floor(pos)).astype(np.float32)

    def window(x):
        return x[i0] * (1.0 - fr) + x[i0 + 1] * fr

    setup = p["black_setup_ire"]
    scale = 100.0 - setup
    y = (window(luma) - setup) / scale
    i = window(i_dem) / scale
    q = window(q_dem) / scale

    phi, gain = _color_lock(chroma, ctx, p, state)     # color reference and color gain for each line
    if p.get("hb_enable"):
        from .hueband import hue_sat_lines
        dphi, g = hue_sat_lines(ctx.n_lines, ctx.offset / 14318181.8, p)
        phi, gain = phi + dphi, gain * g
    phi, gain = phi[src], gain[src][:, None]
    cph, sph = np.cos(phi)[:, None], np.sin(phi)[:, None]
    i, q = i * cph - q * sph, i * sph + q * cph
    i, q = i * gain, q * gain

    if p["sharpness"] > 0:
        y = y + p["sharpness"] * (y - _lp_rows(y, p["sharpness_corner_mhz"], taps))

    rgb = np.stack([y, i, q], axis=-1) @ YIQ2RGB.T
    rgb = np.clip(rgb, 0.0, 1.0)
    return cv2.resize(rgb, (RASTER_W, ACTIVE_LINES), interpolation=cv2.INTER_AREA)
