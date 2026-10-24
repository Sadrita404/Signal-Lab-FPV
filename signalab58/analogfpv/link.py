"""FM radio link, simulated at complex baseband (no 5.8 GHz carrier needed).

    composite (IRE) -> upsample -> FM modulate -> [AIR_STAGES] -> receiver filter
                    -> FM demodulate -> downsample -> composite (IRE)

Brightness steers the carrier frequency: IRE_CENTER maps to the carrier itself and a full
IRE_SPAN (sync tip to white) moves it by `fm_swing_mhz`. The demodulator measures how far the
carrier phase turns between samples, which is why noise-driven phase slips turn into sparkles.
"""
from __future__ import annotations

from functools import lru_cache
from typing import Callable

import numpy as np
from scipy.signal import firwin, oaconvolve, resample_poly

from . import ntsc

IRE_CENTER, IRE_SPAN = 30.0, 140.0
CONTEXT_LINES = 2          # lines of the previous field kept as left context

# Registry of things that damage the radio signal (noise, fading, interference). Each stage is
# fn(x_complex, fs_hz, ctx, params, state) -> x_complex and runs between the modulator and the
# receiver filter, in registration order, when its `enabled(params)` check passes.
AirStage = Callable[[np.ndarray, float, ntsc.FieldCtx, dict, dict], np.ndarray]
AIR_STAGES: list[tuple[str, AirStage, Callable[[dict], bool]]] = []


def register_air_stage(name: str, fn: AirStage, enabled: Callable[[dict], bool]) -> None:
    AIR_STAGES.append((name, fn, enabled))


def effective_swing_mhz(p: dict) -> float:
    """FM swing actually used. With the white glitch off it is capped at what the receiver can pass."""
    swing = p["fm_swing_mhz"]
    if p["fm_white_glitch"]:
        return swing
    return min(swing, p["rx_if_bw_mhz"] / p["fm_fit_ratio"])


def sample_rate(p: dict) -> float:
    return ntsc.FS * p["fm_oversample"]


def fm_modulate(ire: np.ndarray, p: dict) -> np.ndarray:
    n = p["fm_oversample"]
    up = resample_poly(ire.astype(np.float32), n, 1, padtype="edge")
    k = effective_swing_mhz(p) * 1e6 / IRE_SPAN * (2.0 * np.pi / sample_rate(p))   # radians per sample per IRE
    phase = np.mod(np.cumsum(up - np.float32(IRE_CENTER), dtype=np.float64) * k, 2.0 * np.pi).astype(np.float32)
    out = np.empty(phase.size, np.complex64)                    # cos + j sin in single precision (much faster)
    out.real = np.cos(phase)
    out.imag = np.sin(phase)
    return out


@lru_cache(maxsize=8)
def _if_taps(bw_mhz: float, fs: float, ntaps: int) -> np.ndarray:
    return firwin(int(ntaps) | 1, bw_mhz * 1e6 / 2.0, fs=fs).astype(np.float32)


def receiver_filter(x: np.ndarray, p: dict) -> np.ndarray:
    taps = _if_taps(round(p["rx_if_bw_mhz"], 4), sample_rate(p), p["if_filter_taps"])
    return oaconvolve(x, taps, mode="same").astype(np.complex64)


def fm_demodulate(x: np.ndarray, p: dict) -> np.ndarray:
    n = p["fm_oversample"]
    dphi = np.angle(x[1:] * np.conj(x[:-1]))
    dphi = np.concatenate([dphi[:1], dphi])
    freq_hz = dphi * (sample_rate(p) / (2.0 * np.pi))
    ire = IRE_CENTER + freq_hz * (IRE_SPAN / (effective_swing_mhz(p) * 1e6))
    return resample_poly(ire, 1, n, padtype="edge").astype(np.float32)


def fm_link_stage(sig: np.ndarray, ctx: ntsc.FieldCtx, p: dict, state: dict) -> np.ndarray:
    """Channel stage: send one field's composite signal through the whole FM link."""
    flat = sig.reshape(-1).astype(np.float32)
    keep = CONTEXT_LINES * ntsc.SPL
    tail = state.get("fm_tail")
    if tail is None:
        tail = np.zeros(keep, np.float32)                 # nothing before the first field: blanking level
    work = np.concatenate([tail, flat])                   # left context makes field joins seamless
    state["fm_tail"] = flat[-keep:].copy()

    x = fm_modulate(work, p)
    fs = sample_rate(p)
    for _name, air, enabled in AIR_STAGES:
        if enabled(p):
            x = air(x, fs, ctx, p, state)
    x = receiver_filter(x, p)
    ire = fm_demodulate(x, p)
    return ire[keep:].reshape(sig.shape)
