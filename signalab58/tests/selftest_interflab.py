import sys, os, tempfile
import numpy as np
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from interflab import Engine, Patch

def small(**kw):
    return Patch(fs=1e6, spl=100, **kw)

# 1 sine at the right frequency
p = small(); p.add_source(freq_hz=125000.0, amp=1.0)
x = Engine(p).render(65536)
assert np.argmax(np.abs(np.fft.rfft(x))) == 8192, "sine frequency"

# 2 block-by-block equals one big render, with FM + vertical phase patched in
def fm_patch():
    p = small(); a = p.add_source(freq_hz=50000.0, amp=1.0, phase_y=0.003); b = p.add_source(freq_hz=700.0, amp=1.0, to_mix=False)
    c = p.add_source(wave="triangle", freq_hz=90.0, amp=1.0, to_mix=False)
    p.connect(b, a, "freq_hz", 8000.0); p.connect(c, a, "amp", 0.5, "mul"); p.connect(c, a, "phase_x", 0.2)
    return p
big = Engine(fm_patch()).render(40000)
e = Engine(fm_patch()); parts = np.concatenate([e.render(10000) for _ in range(4)])
assert np.allclose(big, parts, atol=1e-6), "block continuity"

# 3 feedback loop and 9th source rejected
p = small(); a = p.add_source(); b = p.add_source(); p.connect(a, b, "amp", 1); p.connect(b, a, "freq_hz", 1)
try: p.validate(); raise SystemExit("cycle not caught")
except ValueError: pass
p = small()
for _ in range(8): p.add_source()
try: p.add_source(); raise SystemExit("9th source accepted")
except ValueError: pass

# 4 gate x sine via 'scale' cable equals sine * gate
p = small(); g = p.add_source(wave="gate", freq_hz=1000.0, amp=1.0, duty=0.5, to_mix=False)
s = p.add_source(freq_hz=33000.0, amp=1.0); p.connect(g, s, "amp", 1.0, "scale")
gated = Engine(p).render(20000)
pg = small(); pg.add_source(wave="gate", freq_hz=1000.0, amp=1.0, duty=0.5); gate = Engine(pg).render(20000)
ps = small(); ps.add_source(freq_hz=33000.0, amp=1.0); sine = Engine(ps).render(20000)
assert set(np.unique(gate)) <= {0.0, 1.0} and 0.2 < gate.mean() < 0.8 and np.allclose(gated, sine * gate), "gate"

# 5 shape ranges, determinism, seeds
for w in ("triangle", "square", "saw", "random"):
    p = small(); p.add_source(wave=w, freq_hz=7777.0, amp=1.0, smooth=0.5); y = Engine(p).render(5000)
    assert y.min() >= -1.0001 and y.max() <= 1.0001, w
def rnd(seed):
    p = small(seed=seed); p.add_source(wave="random", freq_hz=5000.0, amp=1.0); return Engine(p).render(3000)
assert np.array_equal(rnd(1), rnd(1)) and not np.array_equal(rnd(1), rnd(2)), "random seed"

# 6 fade keyframes
p = small(); p.add_source(wave="square", duty=1.0, amp=1.0, fade="0:0, 0.001:1")
f = Engine(p).render(3000); assert abs(f[0]) < 1e-9 and abs(f[2000] - 1) < 1e-9 and 0.4 < f[500] < 0.6, "fade"

# 7 save/load round trip
p = fm_patch(); path = os.path.join(tempfile.gettempdir(), "t_patch.json"); p.save(path)
assert Patch.load(path).to_dict() == p.to_dict(), "json"
print("interflab selftest OK")
