"""Renders a Patch block by block, keeping oscillator phase continuous between blocks."""
import numpy as np

from .patch import MOD_TARGETS, Patch
from .wave import waveform


def parse_fade(text: str):
    """'0:0, 2:1, 5:0' -> (times s, levels), linear in between, held at both ends. Empty -> None."""
    pts = []
    for part in str(text).replace(";", ",").split(","):
        if ":" in part:
            a, b = part.split(":")
            pts.append((float(a), float(b)))
    if not pts:
        return None
    pts.sort()
    return np.array([p[0] for p in pts]), np.array([p[1] for p in pts])


class Engine:
    """eng = Engine(patch); x = eng.render(n) gives the next n samples of the mixed interference."""

    def __init__(self, patch: Patch):
        self.patch = patch
        self.reset()

    def reset(self):
        self.order = self.patch.validate()
        self.pos = 0
        self.state = [dict(phase=0.0, vphase=0.0) for _ in self.patch.sources]
        self.fades = [parse_fade(s["fade"]) for s in self.patch.sources]

    def seek(self, sample: int):
        """Jump to a sample position. Phases restart from zero there (FM phase cannot be reconstructed)."""
        self.reset()
        self.pos = int(sample)

    def render(self, n: int, return_sources: bool = False):
        P = self.patch
        fs, spl = P.fs, P.spl
        gi = self.pos + np.arange(n)
        t = gi / fs
        outs, mix = {}, np.zeros(n)
        for i in self.order:
            s = P.sources[i]
            if not s["enabled"]:
                outs[i] = np.zeros(n)
                continue
            v = {k: s[k] for k in MOD_TARGETS}
            for c in P.cables:
                if c["dst"] != i:
                    continue
                m, d, k = outs[c["src"]], c["depth"], c["param"]
                mode = c.get("mode", "add")
                v[k] = v[k] + d * m if mode == "add" else v[k] * (1.0 + d * m) if mode == "mul" else v[k] * d * m
            st = self.state[i]
            freq = np.broadcast_to(v["freq_hz"], (n,))
            acc = st["phase"] + np.cumsum(freq / fs)
            inc = np.where(gi % spl == 0, np.broadcast_to(v["phase_y"], (n,)), 0.0)
            vph = st["vphase"] + np.cumsum(inc)
            st["phase"], st["vphase"] = float(acc[-1]), float(vph[-1])
            salt = (P.seed * 1000003 + i * 7919 + int(s.get("seed_salt", 0)) + 12345) & ((1 << 63) - 1)
            w = waveform(s["wave"], acc + v["phase_x"] + vph, np.clip(v["duty"], 0.0, 1.0), s["smooth"], salt)
            out = v["offset"] + v["amp"] * w
            if self.fades[i] is not None:
                out = out * np.interp(t, *self.fades[i])
            outs[i] = out
            if s["to_mix"]:
                mix = mix + out
        self.pos += n
        return (mix, outs) if return_sources else mix
