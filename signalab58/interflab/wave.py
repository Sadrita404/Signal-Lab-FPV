"""Waveform shapes on a phase axis (phase in cycles) and a stateless random generator."""
import numpy as np

WAVES = ("sine", "triangle", "square", "saw", "random", "gate")
_MASK = (1 << 64) - 1
_U = np.uint64


def hash_uniform(idx, salt: int) -> np.ndarray:
    """Deterministic uniform [0,1) value for every integer in idx (splitmix64). Same idx -> same value."""
    x = np.atleast_1d(np.asarray(idx)).astype(np.int64).view(np.uint64)
    with np.errstate(over="ignore"):
        x = x + _U((salt * 0x9E3779B97F4A7C15) & _MASK)
        x = (x ^ (x >> _U(30))) * _U(0xBF58476D1CE4E5B9)
        x = (x ^ (x >> _U(27))) * _U(0x94D049BB133111EB)
        x = x ^ (x >> _U(31))
    return (x >> _U(11)).astype(np.float64) * (1.0 / 9007199254740992.0)


def waveform(kind: str, phase: np.ndarray, duty, smooth, salt: int) -> np.ndarray:
    """One cycle per unit of phase. Output -1..1, except 'gate' which is 0 or 1."""
    if kind == "sine":
        return np.sin(2.0 * np.pi * phase)
    if kind == "triangle":
        return 2.0 * np.abs(2.0 * (phase - 0.25 - np.floor(phase - 0.25)) - 1.0) - 1.0
    if kind == "square":
        return np.where(phase - np.floor(phase) < duty, 1.0, -1.0)
    if kind == "saw":
        return 2.0 * (phase - np.floor(phase)) - 1.0
    idx = np.floor(phase)
    if kind == "random":      # a new random value every cycle; smooth>0 glides between them
        a = hash_uniform(idx, salt) * 2.0 - 1.0
        b = hash_uniform(idx + 1, salt) * 2.0 - 1.0
        s = 0.5 - 0.5 * np.cos(np.pi * (phase - idx))
        return a + (b - a) * (smooth * s)
    if kind == "gate":        # random on/off held for whole cycles; duty = chance of 'on'; smooth>0 softens the edges
        a = (hash_uniform(idx, salt) < duty).astype(np.float64)
        if np.all(np.asarray(smooth) == 0):
            return a
        b = (hash_uniform(idx + 1, salt) < duty).astype(np.float64)
        s = 0.5 - 0.5 * np.cos(np.pi * (phase - idx))
        return a + (b - a) * (smooth * s)
    raise ValueError(f"unknown wave {kind!r}")
