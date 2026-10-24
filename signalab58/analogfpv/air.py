"""Over-the-air damage applied to the complex FM signal (registered into link.AIR_STAGES)."""
from __future__ import annotations

import numpy as np
from scipy.signal import lfilter

from . import link, ntsc
from .params import parse_keyframes


LINE_RATE = ntsc.FS / ntsc.SPL        # 15734 lines per second


def fade_db_lines(ctx, p: dict, state: dict) -> np.ndarray:
    """Rician fading, one value (dB, 0 = no fade, negative = signal dipping) per line of this field.

    A smooth random process (carried across fields) is added to a steady direct signal; a low K
    factor means little direct signal, so deep dropouts become common.
    """
    rng = state.setdefault("rng", np.random.default_rng(p["seed"]))
    a = np.exp(-2.0 * np.pi * p["fade_rate_hz"] / LINE_RATE)
    w = (rng.standard_normal(ctx.n_lines) + 1j * rng.standard_normal(ctx.n_lines)) * np.sqrt(0.5 * (1.0 - a * a))
    zi = state.get("fade_zi")
    if zi is None:                                                      # start from a typical value
        zi = np.array([a * (rng.standard_normal() + 1j * rng.standard_normal()) * np.sqrt(0.5)])
    wlp, state["fade_zi"] = lfilter([1.0], [1.0, -a], w, zi=zi)
    k = 10.0 ** (p["fade_k_db"] / 10.0)
    h = np.sqrt(k / (k + 1.0)) + np.sqrt(1.0 / (k + 1.0)) * wlp
    return np.maximum(10.0 * np.log10(np.abs(h) ** 2 + 1e-6), -40.0).astype(np.float32)


BLOCK = 64     # slow-changing values (fading, echo phase, dips) are computed once per 64 samples (~1 us)


def _block_pos(size: int, fs: float) -> np.ndarray:
    """Composite-rate position of the middle of each block, relative to the start of the stage's input."""
    return (np.arange(-(-size // BLOCK)) * BLOCK + BLOCK / 2) * (ntsc.FS / fs)


def _expand(v: np.ndarray, size: int) -> np.ndarray:
    return np.repeat(v, BLOCK)[:size]


def cnr_curve(size: int, fs: float, ctx, p: dict, state: dict | None = None):
    """Signal strength (dB) for every sample: constant or keyframe timeline, plus optional fading."""
    cnr = np.float32(p["link_cnr_db"])
    if ctx is None:
        return cnr
    keep = link.CONTEXT_LINES * ntsc.SPL                               # the stage works on [context + field]
    idx = _block_pos(size, fs)                                          # one value per block, expanded below
    pts = parse_keyframes(p["cnr_keyframes"])
    if pts:
        kt, kv = zip(*pts)
        cnr = np.interp((ctx.offset - keep + idx) / ntsc.FS, kt, kv).astype(np.float32)
    if p["fade_enable"] and state is not None:
        line_pos = (idx - keep) / ntsc.SPL
        cnr = cnr + np.interp(line_pos, np.arange(ctx.n_lines), fade_db_lines(ctx, p, state)).astype(np.float32)
    return cnr if np.ndim(cnr) == 0 else _expand(cnr, size)


def multipath_stage(x: np.ndarray, fs: float, ctx, p: dict, state: dict) -> np.ndarray:
    """Reflections (ground, walls, trees, the pilot): delayed, weaker copies of the radio signal.

    Each echo arrives a little later, so it carries the carrier frequency of a slightly earlier part of
    the picture. Where the picture changes (edges) the two copies disagree and the demodulator outputs
    ghosts, smears and ringing. Moving changes each echo's phase (Doppler), so the copies drift between
    adding up and cancelling: when they cancel, the signal dips and snow, streaks and color errors come
    in bands that roll through the picture.
    """
    shape = state.get("mp_paths")
    if shape is None:                    # random shape of each echo, fixed for the whole render
        rng = np.random.default_rng([p["seed"], 77])
        n = p["mp_paths"] if p["mp_enable"] else 0
        shape = state["mp_paths"] = [((k + 1) / n * rng.uniform(0.6, 1.0), rng.uniform(-1.0, 1.0),
                                      rng.uniform(0.0, 2.0 * np.pi)) for k in range(n)]
        state["mp_phase"] = [ph0 + 2.0 * np.pi * fd * p["mp_doppler_hz"] * ctx.offset / ntsc.FS
                             for _d, fd, ph0 in shape]
    keep = link.CONTEXT_LINES * ntsc.SPL
    rel = (_block_pos(x.size, fs) - keep) / ntsc.FS                     # seconds from this field's start, per block
    g_direct, g_all = dip_gains(x.size, fs, ctx, p, state) if p["dip_enable"] else (None, None)
    out = x * g_direct if g_direct is not None else x.copy()
    for k, (dfrac, fdfrac, _ph0) in enumerate(shape):
        # delay, level and Doppler are read every field, so they can change over time (Parameter links)
        delay_ns, amp, fd = p["mp_delay_ns"] * dfrac, 10.0 ** ((p["mp_level_db"] - 4.0 * k) / 20.0), fdfrac * p["mp_doppler_hz"]
        ph = state["mp_phase"][k]
        state["mp_phase"][k] = ph + 2.0 * np.pi * fd * ctx.n_lines * ntsc.SPL / ntsc.FS
        d = delay_ns * 1e-9 * fs
        i0, fr = int(d), np.float32(d - int(d))
        xp = np.concatenate([np.full(i0 + 1, x[0], x.dtype), x])         # delayed copies are slices of this
        rot = _expand(np.exp(1j * (2.0 * np.pi * fd * rel + ph)).astype(np.complex64) * np.float32(amp), x.size)
        out += rot * ((1.0 - fr) * xp[1:1 + x.size] + fr * xp[:x.size])
    if g_all is not None:
        out *= g_all
    return out


def dip_gains(size: int, fs: float, ctx, p: dict, state: dict):
    """Short signal dips (flying behind something), as per-sample gains (direct path, whole signal).

    Each dip: the direct path fades away faster and faster over `dip_approach_lines` while the reflections
    stay, so they take over and the hue shift grows; then the whole signal drops for `dip_static_lines`
    (static) and comes straight back. Dips start at random, `dip_rate_hz` per second on average.
    """
    rng = state.setdefault("dip_rng", np.random.default_rng([p["seed"], 91]))
    keep = link.CONTEXT_LINES * ntsc.SPL
    line = (ctx.offset - keep + _block_pos(size, fs)) / ntsc.SPL                # global line position per block
    events, nxt = state.get("dip_events", []), state.get("dip_next")
    if nxt is None:
        nxt = line[0] + rng.exponential(LINE_RATE / p["dip_rate_hz"])
    while nxt < line[-1]:
        a = rng.uniform(0.5, 1.5) * p["dip_approach_lines"]
        b = max(1.0, rng.uniform(0.5, 1.5) * p["dip_static_lines"])
        events.append((nxt, a, b))
        nxt += a + b + rng.exponential(LINE_RATE / p["dip_rate_hz"])
    events = [e for e in events if e[0] + e[1] + e[2] > line[0]]
    state["dip_events"], state["dip_next"] = events, nxt
    if not any(e[0] < line[-1] for e in events):
        return None, None                                                   # no dip in this field
    db_dir = np.zeros(line.size)
    db_all = np.zeros(line.size)
    for s0, a, b in events:
        u = line - s0
        ramp = (u >= 0) & (u < a)
        db_dir[ramp] -= p["dip_direct_db"] * np.expm1(3.0 * u[ramp] / a) / np.expm1(3.0)   # slow start, then fast
        hole = (u >= a) & (u < a + b)
        db_dir[hole] -= p["dip_direct_db"]
        db_all[hole] -= p["dip_static_db"]
    return (_expand((10.0 ** (db_dir / 20.0)).astype(np.float32), size),
            _expand((10.0 ** (db_all / 20.0)).astype(np.float32), size))


link.register_air_stage("multipath", multipath_stage, lambda p: p["mp_enable"] or p["dip_enable"])


def noise_stage(x: np.ndarray, fs: float, ctx, p: dict, state: dict) -> np.ndarray:
    """Add white Gaussian radio noise.

    `link_cnr_db` is the carrier-to-noise ratio measured over a fixed reference bandwidth, so a
    narrower receiver filter really does let in less noise. Because the demodulator measures the
    carrier's phase, noise that is strong enough to spin the phase a full turn comes out as the
    white and black sparkles of FM "snow".
    """
    rng = state.setdefault("rng", np.random.default_rng(p["seed"]))
    cnr_db = cnr_curve(x.size, fs, ctx, p, state)                            # per-sample dB, or one number
    noise_to_carrier = 10.0 ** (-np.asarray(cnr_db, np.float32) / np.float32(10.0))
    power = noise_to_carrier * np.float32(fs / (p["noise_ref_bw_mhz"] * 1e6))   # per sample at the wide rate
    scale = np.sqrt(power / np.float32(2.0))
    return x + scale * _noise(rng, x.size, state)


NOISE_BANK = 1 << 22        # complex samples of white noise made once; each field reads a random stretch of it


def _noise(rng, size: int, state: dict) -> np.ndarray:
    """Unit-power complex white noise. Drawing fresh noise every field was the slowest step; a random stretch of a
    big pre-made bank is statistically the same and impossible to tell apart in the picture."""
    bank = state.get("noise_bank")
    if bank is None or bank.size < 2 * size:
        bank = state["noise_bank"] = rng.standard_normal(2 * max(NOISE_BANK, 2 * size), dtype=np.float32).view(np.complex64)
    start = int(rng.integers(0, bank.size - size))
    return bank[start:start + size]


link.register_air_stage("noise", noise_stage, lambda p: p["noise_enable"])


def interferer_stage(x: np.ndarray, fs: float, ctx, p: dict, state: dict) -> np.ndarray:
    """Add a single-frequency interferer.

    The interferer sits at a fixed radio frequency, while the carrier moves with the picture, so the
    beat tone seen in the video depends on brightness. `intf_offset_mhz` is where the tone lands while
    the carrier rests at blanking level, which is where the sync and color burst live. At 3.58 MHz it
    sits on the color burst, so the goggles' burst lock rotates the hue of each line; the small detune
    sets how fast that rotation changes from line to line (thick flat bands when small). Brighter
    picture areas shift the tone away from 3.58 MHz, so bright and dark areas are hit differently.
    """
    keep = link.CONTEXT_LINES * ntsc.SPL
    idx = np.arange(x.size, dtype=np.float64) * (ntsc.FS / fs)
    t = (ctx.offset - keep + idx) / ntsc.FS                    # absolute seconds: continuous across fields
    f_blank_hz = (0.0 - link.IRE_CENTER) * link.effective_swing_mhz(p) * 1e6 / link.IRE_SPAN   # carrier at blanking
    f0 = f_blank_hz + p["intf_offset_mhz"] * 1e6 + p["intf_detune_hz"]
    phase = 2.0 * np.pi * f0 * t

    if p["intf_wander_hz"] > 0:                                # slow random frequency drift (per line)
        rng = state.setdefault("rng", np.random.default_rng(p["seed"]))
        n = ctx.n_lines
        a = np.exp(-(1.0 / LINE_RATE) / p["intf_wander_tau_s"])
        w = rng.standard_normal(n) * p["intf_wander_hz"] * np.sqrt(1.0 - a * a)
        df, prev = np.empty(n), state.get("intf_df", 0.0)
        for i in range(n):
            prev = a * prev + w[i]
            df[i] = prev
        state["intf_df"] = prev
        theta = state.get("intf_theta", 0.0) + np.concatenate([[0.0], np.cumsum(2.0 * np.pi * df / LINE_RATE)])
        state["intf_theta"] = theta[-1]
        phase = phase + np.interp((idx - keep) / ntsc.SPL, np.arange(n + 1), theta)

    amp = np.float32(10.0 ** (p["intf_level_db"] / 20.0))
    return x + amp * np.exp(1j * np.mod(phase, 2.0 * np.pi)).astype(np.complex64)


link.register_air_stage("interferer", interferer_stage, lambda p: p["intf_enable"])
