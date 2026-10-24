"""Quick checks for the clean signal path. Run:  python tests/selftest.py"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
import numpy as np

from analogfpv import air, link, ntsc, params, pipeline

# the defaults include noise, fading and reflections now; these checks are about the clean signal path
p = dict(params.defaults(), noise_enable=False, fade_enable=False, mp_enable=False, dip_enable=False)
cols = np.array([[1, 1, 1], [1, 1, 0], [0, 1, 1], [0, 1, 0], [1, 0, 1], [1, 0, 0], [0, 0, 1], [0, 0, 0]], np.float32) * 0.75
rgb = np.tile(np.repeat(cols, 80, axis=0)[None], (240, 1, 1))
mask = np.zeros(640, bool)
for b in range(8):
    mask[b * 80 + 30:b * 80 + 50] = True

# 1. round trip over several consecutive fields (checks subcarrier phase stays continuous).
#    The goggles' color PLL has its own small drift on purpose, so it is switched off for this exact check.
offset = 0
p_rt = dict(p, burst_lock=False)
for idx in range(4):
    ctx = ntsc.FieldCtx(idx, idx & 1, ntsc.LINES[idx & 1], offset)
    sig = ntsc.encode_field(rgb, ctx, p_rt)
    out = ntsc.decode_field(sig, ctx, p_rt)
    err = np.abs(out - rgb)[:, mask].mean()
    assert err < 0.01, f"field {idx}: round-trip error {err:.4f}"
    offset += ctx.n_lines * ntsc.SPL

# 2. sync and burst structure
ctx = ntsc.FieldCtx(0, 0, 262, 0)
sig = ntsc.encode_field(rgb, ctx, p)
S, H, B = p["sync_level_ire"], p["hsync_len"], p["burst_amp_ire"]
assert sig.min() == S
assert np.all(sig[100, :H] == S) and sig[100, H + 2] > S
burst = sig[100, ntsc.BURST_START:ntsc.BURST_START + 4 * p["burst_cycles"]]
assert abs(burst.max() - B) < 1e-3 and abs(burst.min() + B) < 1e-3
assert sig[4, 10] == S and sig[4, 300] == S and sig[4, 500] == S  # broad vsync pulses
assert sig[4, 420] == 0 and sig[4, 880] == 0                              # ...with serrations
assert ntsc.LINES[0] + ntsc.LINES[1] == 525

# 2b. FM link: near-transparent at defaults, softer with a narrow receiver filter, bypassable
state, offset = {}, 0
for idx in range(3):
    ctx = ntsc.FieldCtx(idx, idx & 1, ntsc.LINES[idx & 1], offset)
    clean = ntsc.encode_field(rgb, ctx, p)
    sent = link.fm_link_stage(clean, ctx, p, state)
    assert sent.shape == clean.shape
    rms = float(np.sqrt(np.mean((sent - clean) ** 2)))
    assert rms < 1.0, f"FM link not transparent: {rms:.2f} IRE RMS"
    offset += ctx.n_lines * ntsc.SPL
narrow = dict(p, rx_if_bw_mhz=8.0)
ctx = ntsc.FieldCtx(0, 0, 262, 0)
soft = link.fm_link_stage(ntsc.encode_field(rgb, ctx, p), ctx, narrow, {})
assert np.sqrt(np.mean((soft - ntsc.encode_field(rgb, ctx, p)) ** 2)) > 3 * rms
assert not pipeline.Pipeline({"fm_enable": False}).channel_stages
assert len(pipeline.Pipeline({"fm_enable": True}).channel_stages) == 1

# 2c. white glitch toggle: off caps the swing to what the receiver passes
assert link.effective_swing_mhz(dict(p, rx_if_bw_mhz=6, fm_swing_mhz=30)) == 30
assert abs(link.effective_swing_mhz(dict(p, rx_if_bw_mhz=6, fm_swing_mhz=30, fm_white_glitch=False)) - 7.5) < 1e-6
assert link.effective_swing_mhz(dict(p, fm_white_glitch=False)) == p["fm_swing_mhz"]   # defaults unaffected

# 2d. noise stage: measured carrier-to-noise ratio matches the setting
q = dict(p, link_cnr_db=10.0, noise_ref_bw_mhz=20.0, rx_if_bw_mhz=20.0)
x = np.ones(200_000, np.complex64)
y = link.receiver_filter(air.noise_stage(x, link.sample_rate(q), None, q, {"rng": np.random.default_rng(1)}), q)
measured = -10 * np.log10(np.mean(np.abs(y[3000:-3000] - 1) ** 2))
assert abs(measured - 10.0) < 1.0, f"noise calibration off: {measured:.2f} dB"
assert any(n == "noise" for n, _, _ in link.AIR_STAGES)

# 2e. signal-strength timeline: clean at the start, noisy at the end, parsed and validated
assert params.parse_keyframes("5:12, 0:40") == [(0.0, 40.0), (5.0, 12.0)]
q = dict(p, cnr_keyframes="0:60, 0.03:6", noise_ref_bw_mhz=20.0)
x = np.ones(2_000_000, np.complex64)
y = air.noise_stage(x, link.sample_rate(q), ntsc.FieldCtx(0, 0, 262, 0), q, {"rng": np.random.default_rng(2)})
early, late = np.mean(np.abs(y[:100_000] - 1) ** 2), np.mean(np.abs(y[-100_000:] - 1) ** 2)
assert late > 100 * early, f"timeline not applied: {early:.2e} vs {late:.2e}"

# 2f. random fading: deeper dips with a low K factor, gentle with a high one, continuous across fields
def fade_stats(k_db):
    q, st, vals = dict(p, fade_enable=True, fade_k_db=k_db, fade_rate_hz=3.0), {"rng": np.random.default_rng(5)}, []
    for i in range(120):
        vals.append(air.fade_db_lines(ntsc.FieldCtx(i, i & 1, ntsc.LINES[i & 1], 0), q, st))
    v = np.concatenate(vals)
    return v.std(), v.min()
deep_std, deep_min = fade_stats(-10.0)
calm_std, calm_min = fade_stats(30.0)
assert deep_std > 3 * calm_std and deep_min < -10 and calm_min > -2, (deep_std, deep_min, calm_std, calm_min)

# 2g. burst lock: a 90-degree phase error on the whole line (1-sample delay) is corrected only with lock on
ctx = ntsc.FieldCtx(0, 0, 262, 0)
sig = ntsc.encode_field(rgb, ctx, p)
shifted = np.roll(sig.reshape(-1), 1).reshape(sig.shape)
ref = ntsc.decode_field(sig, ctx, p)
locked = ntsc.decode_field(shifted, ctx, p, state={})
unlocked = ntsc.decode_field(shifted, ctx, dict(p, burst_lock=False))
err_on = np.abs(locked - ref)[:, mask].mean()
err_off = np.abs(unlocked - ref)[:, mask].mean()
assert err_on < 0.03 and err_off > 0.1, (err_on, err_off)
tint = ntsc.decode_field(sig, ctx, dict(p, hue_offset_deg=90.0))
assert np.abs(tint - ref)[:, mask].mean() > 0.1

# 2h. interferer: after FM demodulation it appears as a video tone of the predicted size
q = dict(p, noise_enable=False, intf_enable=True, intf_level_db=-12.0, intf_offset_mhz=ntsc.FS / 4 / 1e6)
ctx = ntsc.FieldCtx(0, 0, 262, 0)
clean = np.zeros((262, ntsc.SPL), np.float32)                   # flat blanking level: beat is exactly the offset
hit = link.fm_link_stage(clean, ctx, q, {})
d = (hit - clean).reshape(-1)[40_000:200_000]
n_idx = np.arange(d.size) + 40_000
tone = 2 * np.abs(np.sum(d * np.exp(-1j * np.pi / 2 * n_idx))) / d.size       # FS/4 tone amplitude, IRE
expected = 140.0 * 10 ** (-12 / 20) * (ntsc.FS / 4 / 1e6) / p["fm_swing_mhz"]
assert 0.7 * expected < tone < 1.3 * expected, (tone, expected)

# 3. parameter validation
for bad in ({"luma_bw_mhz": 99}, {"nope": 1}, {"deinterlace": "x"}, {"hsync_len": 76}, {"burst_cycles": 20}, {"rx_if_bw_mhz": 3}, {"cnr_keyframes": "oops"}, {"cnr_keyframes": "0:99"}):
    try:
        params.validate(bad)
    except (ValueError, KeyError):
        pass
    else:
        raise AssertionError(f"accepted bad params {bad}")

# 4. pipeline shape/type, both deinterlace modes
img = (np.random.default_rng(0).random((480, 640, 3)) * 255).astype(np.uint8)
for mode in ("bob", "weave"):
    out = pipeline.process_still(img, {"deinterlace": mode}, fields=3)
    assert out.shape == (480, 640, 3) and out.dtype == np.uint8
print("selftest OK")
