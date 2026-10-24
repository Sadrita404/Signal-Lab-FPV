"""Patch = up to 8 sources + cables (modular-synth style). Plain dicts, so a GUI can edit and save them directly."""
import json
from copy import deepcopy

MAX_SOURCES = 8
FS_DEFAULT = 4 * 3579545.4545          # 4x color subcarrier, the analogfpv sample rate
SPL_DEFAULT = 910                      # samples per line

# name, default, min, max, step, unit, modulatable, help   (a GUI builds its sliders from this)
SOURCE_SCHEMA = [
    ("freq_hz", 3579545.0, -20e6, 20e6, 1.0, "Hz", True, "Oscillator frequency. Random/gate waves pick a new value once per cycle."),
    ("amp", 0.1, 0.0, 10.0, 0.01, "", True, "Output size (units depend on where the patch is injected)."),
    ("offset", 0.0, -10.0, 10.0, 0.01, "", True, "Constant added to the wave before the fade; a very slow big source here pushes the whole signal."),
    ("phase_x", 0.0, -1.0, 1.0, 0.001, "cycles", True, "Phase left/right: shifts the wave sideways along the line (phase modulation when patched)."),
    ("phase_y", 0.0, -1.0, 1.0, 0.0001, "cyc/line", True, "Phase up/down: extra phase gained on every new line, so the pattern creeps vertically."),
    ("duty", 0.5, 0.0, 1.0, 0.01, "", True, "Square: high fraction. Gate: chance a cycle is 'on'."),
    ("smooth", 0.0, 0.0, 1.0, 0.05, "", False, "Random and gate waves: 0 = hard steps, 1 = smooth glide (soft band edges)."),
]
MOD_TARGETS = tuple(r[0] for r in SOURCE_SCHEMA if r[6])
CABLE_MODES = ("add", "mul", "scale")   # base+d*m | base*(1+d*m) | base*d*m (VCA, good with gates)


def new_source(**kw) -> dict:
    s = {r[0]: r[1] for r in SOURCE_SCHEMA}
    s.update(name="", enabled=True, wave="sine", to_mix=True, fade="", seed_salt=0)
    s.update(kw)
    return s


class Patch:
    def __init__(self, fs=FS_DEFAULT, spl=SPL_DEFAULT, seed=0):
        self.fs, self.spl, self.seed = float(fs), int(spl), int(seed)
        self.sources: list[dict] = []
        self.cables: list[dict] = []

    # -- editing
    def add_source(self, **kw) -> int:
        if len(self.sources) >= MAX_SOURCES:
            raise ValueError(f"at most {MAX_SOURCES} sources")
        self.sources.append(new_source(**kw))
        if not self.sources[-1]["name"]:
            self.sources[-1]["name"] = f"src{len(self.sources)}"
        return len(self.sources) - 1

    def connect(self, src: int, dst: int, param: str, depth: float, mode: str = "add"):
        """Plug the output of source `src` into parameter `param` of source `dst`."""
        self.cables.append(dict(src=int(src), dst=int(dst), param=param, depth=float(depth), mode=mode))

    def validate(self) -> list[int]:
        """Check the patch; return the order sources must be computed in (modulators first)."""
        from .wave import WAVES
        n = len(self.sources)
        if n > MAX_SOURCES:
            raise ValueError(f"at most {MAX_SOURCES} sources")
        for s in self.sources:
            if s["wave"] not in WAVES:
                raise ValueError(f"unknown wave {s['wave']!r}")
        deps = {i: set() for i in range(n)}
        for c in self.cables:
            if not (0 <= c["src"] < n and 0 <= c["dst"] < n):
                raise ValueError(f"cable points at a missing source: {c}")
            if c["param"] not in MOD_TARGETS:
                raise ValueError(f"cannot modulate {c['param']!r}; choose from {MOD_TARGETS}")
            if c.get("mode", "add") not in CABLE_MODES:
                raise ValueError(f"unknown cable mode {c.get('mode')!r}")
            deps[c["dst"]].add(c["src"])
        order, done = [], set()
        while len(order) < n:
            ready = [i for i in range(n) if i not in done and deps[i] <= done]
            if not ready:
                raise ValueError("patch has a feedback loop (a source modulating itself through other sources)")
            for i in ready:
                order.append(i)
                done.add(i)
        return order

    # -- save / load
    def to_dict(self) -> dict:
        return deepcopy(dict(fs=self.fs, spl=self.spl, seed=self.seed, sources=self.sources, cables=self.cables))

    @classmethod
    def from_dict(cls, d: dict) -> "Patch":
        p = cls(d.get("fs", FS_DEFAULT), d.get("spl", SPL_DEFAULT), d.get("seed", 0))
        for s in d.get("sources", []):
            p.add_source(**s)
        p.cables = [dict(c) for c in d.get("cables", [])]
        p.validate()
        return p

    def save(self, path: str):
        with open(path, "w") as f:
            json.dump(self.to_dict(), f, indent=1)

    @classmethod
    def load(cls, path: str) -> "Patch":
        with open(path) as f:
            return cls.from_dict(json.load(f))
