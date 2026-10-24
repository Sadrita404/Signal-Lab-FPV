"""Starter patches. Amplitude units are arbitrary until the analogfpv adapter (step 3) fixes the scale."""
from .patch import Patch

FSC = 3579545.0


def tone_burst() -> Patch:
    """Short bursts of a color-subcarrier tone, random start, random length: the one-frame band recipe."""
    p = Patch()
    jitter = p.add_source(name="length jitter", wave="random", freq_hz=3000.0, amp=1.0, smooth=0.0, to_mix=False)
    gate = p.add_source(name="gate", wave="gate", freq_hz=1500.0, amp=1.0, duty=0.15, to_mix=False)
    tone = p.add_source(name="tone", wave="sine", freq_hz=FSC, amp=0.3)
    p.connect(jitter, gate, "freq_hz", 900.0)       # varies how long each on/off stretch lasts
    p.connect(gate, tone, "amp", 1.0, "scale")      # tone only while the gate is on
    return p


def slow_push() -> Patch:
    """Very low frequency wave pushing the whole signal up and down, with a small triangle clashing on top."""
    p = Patch()
    p.add_source(name="push", wave="sine", freq_hz=0.7, amp=1.0)
    p.add_source(name="clash", wave="triangle", freq_hz=95.0, amp=0.25)
    return p


def noisy_fm_tone() -> Patch:
    """A tone near the subcarrier whose frequency wanders randomly (sine with noise modulated onto it)."""
    p = Patch()
    noise = p.add_source(name="noise", wave="random", freq_hz=20000.0, amp=1.0, smooth=0.5, to_mix=False)
    tone = p.add_source(name="tone", wave="sine", freq_hz=FSC, amp=0.15, phase_y=0.002)
    p.connect(noise, tone, "freq_hz", 300000.0)
    return p


def vertical_creep() -> Patch:
    """One steady tone whose pattern slowly climbs the screen (phase up/down)."""
    p = Patch()
    p.add_source(name="tone", wave="sine", freq_hz=FSC, amp=0.2, phase_y=0.003)
    return p


EXAMPLES = dict(tone_burst=tone_burst, slow_push=slow_push, noisy_fm_tone=noisy_fm_tone, vertical_creep=vertical_creep)
