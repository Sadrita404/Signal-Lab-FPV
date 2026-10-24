"""Parameter schema.

Every user-facing setting is declared ONCE here. The command line, preset files
and any future GUI (sliders, dropdowns, checkboxes) are generated from this list,
so adding an effect later means adding one `Param` entry.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any


@dataclass(frozen=True)
class Param:
    key: str
    label: str
    group: str
    kind: str                      # "float" | "int" | "bool" | "choice"
    default: Any
    min: float | None = None
    max: float | None = None
    step: float | None = None
    choices: tuple = ()
    unit: str = ""
    help: str = ""
    advanced: bool = False


PARAMS: list[Param] = [
    # ---- Input ----------------------------------------------------------
    Param("fit_mode", "Fit to 4:3", "Input", "choice", "crop",
          choices=("crop", "pad", "stretch"),
          help="How non-4:3 input is fitted to the 640x480 analog raster."),

    # ---- Camera/VTX video encoder ---------------------------------------
    Param("luma_bw_mhz", "Luma bandwidth", "Encoder", "float", 4.2, 2.0, 5.5, 0.1, unit="MHz",
          help="Low-pass on brightness before the signal is made. Lower = softer picture."),
    Param("i_bw_mhz", "Chroma I bandwidth", "Encoder", "float", 1.3, 0.3, 2.0, 0.05, unit="MHz",
          help="Orange-cyan color detail. NTSC standard is about 1.3 MHz."),
    Param("q_bw_mhz", "Chroma Q bandwidth", "Encoder", "float", 0.5, 0.2, 1.5, 0.05, unit="MHz",
          help="Green-magenta color detail. NTSC standard is about 0.5 MHz."),
    Param("black_setup_ire", "Black setup", "Encoder", "float", 7.5, 0.0, 10.0, 0.5, unit="IRE",
          help="Black level above blanking (7.5 = NTSC-M, 0 = NTSC-J)."),
    Param("composite_clip_ire", "Peak clip", "Encoder", "float", 120.0, 100.0, 140.0, 1.0, unit="IRE",
          help="Highest level the video amplifier allows (saturated colors can exceed 100 IRE)."),

    # ---- Advanced encoder values (previously hardcoded) --------------------------
    Param("sync_level_ire", "Sync tip level", "Encoder", "float", -40.0, -60.0, -10.0, 1.0, unit="IRE",
          advanced=True, help="Level of the sync pulses (standard -40)."),
    Param("burst_amp_ire", "Color burst amplitude", "Encoder", "float", 20.0, 0.0, 40.0, 1.0, unit="IRE",
          advanced=True, help="Peak amplitude of the color burst (standard 20)."),
    Param("hsync_len", "Horizontal sync width", "Encoder", "int", 67, 40, 74, 1, unit="samples",
          advanced=True, help="Sync pulse width in samples of the 14.3 MHz clock (67 = 4.7 us)."),
    Param("burst_cycles", "Burst length", "Encoder", "int", 9, 4, 12, 1, unit="cycles",
          advanced=True, help="Number of subcarrier cycles in the color burst (standard 9)."),
    Param("filter_taps", "Filter length", "Encoder", "int", 63, 15, 255, 2, unit="taps",
          advanced=True, help="Length of the FIR filters used for bandwidth limiting (odd numbers; longer = sharper cutoff)."),

    # ---- VTX / radio link ------------------------------------------------------------
    Param("fm_enable", "FM radio link", "Link", "bool", True,
          help="Send the signal through the simulated FM link (off = skip the radio stage)."),
    Param("fm_swing_mhz", "FM frequency swing", "VTX", "float", 12.0, 4.0, 30.0, 0.5, unit="MHz",
          help="Carrier frequency swing for a full sync-tip-to-white signal (140 IRE). Typical VTXs are around 10-14 MHz."),
    Param("fm_white_glitch", "White-to-color glitch", "Link", "bool", True,
          help="On: if the receiver filter is too narrow for the FM swing it clips peak white and bright areas "
               "break into colored patches (seen on some goggles). Off: the swing is automatically limited so "
               "the receiver always passes it and whites stay clean."),
    Param("fm_fit_ratio", "Glitch threshold ratio", "Link", "float", 0.8, 0.5, 1.2, 0.05,
          advanced=True, help="The glitch starts when receiver bandwidth falls below this fraction of the FM swing "
                              "(also sets the automatic limit when the glitch is off)."),
    Param("noise_enable", "Radio noise", "Link", "bool", True, help="Add noise to the radio signal (snow)."),
    Param("link_cnr_db", "Signal strength (CNR)", "Link", "float", 25.0, -5.0, 60.0, 0.5, unit="dB",
          help="Carrier-to-noise ratio at the receiver. Lower = more snow."),
    Param("cnr_keyframes", "Signal strength timeline", "Link", "text", "",
          help="Signal strength over time as time_seconds:dB points, for example \"0:40, 5:40, 8:12, 12:8, 14:40\". "
               "Straight lines between points, first/last value held. Empty = constant link_cnr_db."),
    Param("fade_enable", "Random fading", "Link", "bool", True,
          help="Add random signal-strength wobble on top of the timeline (shows up as snow coming and going)."),
    Param("fade_k_db", "Fading steadiness (Rician K)", "Link", "float", 6.0, -10.0, 30.0, 1.0, unit="dB",
          help="High = gentle wobble. Low = frequent deep dropouts. -10 is the worst case (no direct signal)."),
    Param("fade_rate_hz", "Fading speed", "Link", "float", 3.0, 0.1, 100.0, 0.1, unit="Hz",
          help="How fast the wobble changes (flying fast or through clutter = faster)."),
    Param("mp_enable", "Multipath (reflections)", "Link", "bool", True,
          help="Add delayed copies of the radio signal bouncing off the ground, walls and trees: ghosts, smeared "
               "edges, and bands of snow and color errors where the copies cancel."),
    Param("mp_paths", "Number of reflections", "Link", "int", 2, 1, 4, 1,
          help="How many echoes arrive (each one later and weaker than the last)."),
    Param("mp_level_db", "Reflection strength", "Link", "float", -4.0, -30.0, 0.0, 0.5, unit="dB",
          help="Strongest echo relative to the direct signal. Near 0 dB = deep cancellations (indoors, low over water)."),
    Param("mp_delay_ns", "Reflection delay", "Link", "float", 100.0, 20.0, 3000.0, 10.0, unit="ns",
          help="How late the last echo arrives. ~70 ns is one composite sample; 300 ns is about 90 m extra path."),
    Param("mp_doppler_hz", "Reflection drift", "Link", "float", 25.0, 0.0, 500.0, 1.0, unit="Hz",
          help="How fast the echoes slide in and out of phase as you move. 0 = hovering (frozen), "
               "higher = cancellation bands rolling faster."),
    Param("dip_enable", "Static dips", "Link", "bool", False,
          help="Short dips where the direct signal fades away (flying behind something): the hue shift grows line by "
               "line as the reflections take over, then a few lines of static, then back to normal. Use with multipath."),
    Param("dip_rate_hz", "Dips per second", "Link", "float", 1.0, 0.05, 20.0, 0.05, unit="/s",
          help="Average number of dips per second (they come at random)."),
    Param("dip_approach_lines", "Dip build-up", "Link", "float", 40.0, 2.0, 250.0, 1.0, unit="lines",
          help="Lines over which the hue shift builds up before the static (randomized +-50%)."),
    Param("dip_static_lines", "Dip static height", "Link", "float", 5.0, 1.0, 60.0, 1.0, unit="lines",
          help="Lines of static at the bottom of the dip (randomized +-50%). 1 line = 2 rows of the output."),
    Param("dip_direct_db", "Dip direct-signal loss", "Link", "float", 15.0, 0.0, 40.0, 1.0, unit="dB",
          help="How far the direct signal falls during the build-up. More = bigger hue shift before the static."),
    Param("dip_static_db", "Dip depth", "Link", "float", 28.0, 0.0, 50.0, 1.0, unit="dB",
          help="How far the whole signal falls in the static part. Static appears once signal strength minus this "
               "is below roughly 10 dB."),
    Param("intf_enable", "Narrowband interferer", "Link", "bool", False,
          help="Add a single-frequency interfering signal (another transmitter or spur) near your channel."),
    Param("intf_offset_mhz", "Interferer beat frequency", "Link", "float", 3.579545, -25.0, 25.0, 0.001, unit="MHz",
          help="Frequency of the interferer's beat tone in the video while the picture is at blanking level. "
               "3.58 MHz sits on the color burst and rotates hue; other values give diagonal bars or fine patterns. "
               "Brighter picture areas shift the tone, as in real FM."),
    Param("intf_detune_hz", "Interferer fine detune", "Link", "float", 0.0, -20000.0, 20000.0, 10.0, unit="Hz",
          help="Tiny extra offset. Small values (tens to hundreds of Hz) turn hue bands into slow, thick bands; "
               "larger values give thinner bands and diagonal rainbow stripes."),
    Param("intf_level_db", "Interferer strength", "Link", "float", -12.0, -60.0, 6.0, 1.0, unit="dB",
          help="Interferer power relative to your signal. Around -12 to -6 gives strong effects; above 0 it captures the receiver."),
    Param("intf_wander_hz", "Interferer frequency wander", "Link", "float", 0.0, 0.0, 5000.0, 10.0, unit="Hz",
          help="How much the interferer's frequency drifts (free-running oscillators drift). Makes the bands creep and change from frame to frame."),
    Param("intf_wander_tau_s", "Wander time scale", "Link", "float", 0.3, 0.01, 10.0, 0.01, unit="s",
          advanced=True, help="How quickly the drift direction changes."),
    Param("if2_enable", "interflab interference", "Interference", "bool", False,
          help="Add an interference patch made in interflab. The goggles' decoder turns it into hue bands, "
               "tints and stripes on its own (burst lock and color demodulation)."),
    Param("if2_patch", "interflab patch", "Interference", "text", "tone_burst",
          help="Path to a patch .json, or the name of one in the patches folder (tone_burst, slow_push, ...)."),
    Param("if2_mode", "Injection point", "Interference", "choice", "video", choices=("video",),
          help="video: added to the received video signal right before the goggles' decoder. "
               "(A radio-level mode comes later.)"),
    Param("mod_links", "Parameter links", "Interference", "text", "", advanced=True,
          help="interflab sources set to Parameter that drive settings over time, as JSON: "
               '[{"src": "lfo", "param": "link_cnr_db", "mode": "add", "amount": 1}]. '
               "mode replace = setting becomes the source value, add = added to the setting. "
               "Uses the patch in if2_patch. The GUI makes these by dragging the patch dots onto a setting."),
    Param("if2_scale_ire", "Patch strength", "Interference", "float", 20.0, 0.0, 140.0, 0.5, unit="IRE",
          help="IRE per patch unit. 20 = a patch value of 1 is as big as the color burst."),
    Param("noise_ref_bw_mhz", "Noise reference bandwidth", "Link", "float", 20.0, 5.0, 50.0, 0.5, unit="MHz",
          advanced=True, help="Bandwidth the signal strength is measured in; the receiver filter width then decides how much noise gets through."),
    Param("fm_oversample", "FM oversampling", "Link", "int", 3, 2, 8, 1, unit="x",
          advanced=True, help="Simulation sample rate for the radio stage as a multiple of 14.3 MHz."),
    Param("rx_if_bw_mhz", "Receiver bandwidth", "Goggles", "float", 22.0, 6.0, 40.0, 0.5, unit="MHz",
          help="Width of the receiver's radio filter. Narrow = less noise but softer, wide = sharper but noisier."),
    Param("if_filter_taps", "Receiver filter length", "Goggles", "int", 129, 31, 511, 2, unit="taps",
          advanced=True, help="Length of the receiver radio filter (longer = sharper edges)."),

    # ---- Goggles / decoder -----------------------------------------------
    Param("rx_clip_enable", "Goggle input clipping", "Goggles", "bool", True,
          help="The goggles' video input can only take a limited voltage range. Signal pushed past it is cut flat, "
               "which also flattens the color riding on it (bright pushes wash out, dark pushes lose color)."),
    Param("rx_clip_high_ire", "Input clip top", "Goggles", "float", 125.0, 90.0, 160.0, 1.0, unit="IRE",
          help="Highest level the goggles' input passes. Lower = color drains sooner on bright pushes."),
    Param("rx_clip_low_ire", "Input clip bottom", "Goggles", "float", -45.0, -80.0, 0.0, 1.0, unit="IRE",
          help="Lowest level the goggles' input passes (sync tips sit at -40)."),
    Param("comb_amount", "Comb filter amount", "Goggles", "float", 0.0, 0.0, 1.0, 0.05,
          help="Luma/chroma separation: 0 = simple notch filter (soft color edges, little dot crawl), "
               "1 = line comb filter (sharper, but cross-color and dot crawl on vertical detail)."),
    Param("dec_chroma_bw_mhz", "Decoder chroma bandwidth", "Goggles", "float", 1.0, 0.3, 1.5, 0.05, unit="MHz",
          help="Color detail the goggles' decoder keeps."),
    Param("sharpness", "Sharpness (peaking)", "Goggles", "float", 0.0, 0.0, 1.5, 0.05,
          help="Edge peaking on brightness. Too high adds ringing halos."),
    Param("chroma_bp_low_mhz", "Chroma band-pass low edge", "Goggles", "float", 2.2, 1.0, 3.4, 0.1, unit="MHz",
          advanced=True, help="Lower edge of the filter that picks the color signal out of the video."),
    Param("chroma_bp_high_mhz", "Chroma band-pass high edge", "Goggles", "float", 4.4, 3.7, 6.0, 0.1, unit="MHz",
          advanced=True, help="Upper edge of the chroma filter."),
    Param("sharpness_corner_mhz", "Sharpness corner", "Goggles", "float", 2.0, 0.5, 4.0, 0.1, unit="MHz",
          advanced=True, help="Detail above this frequency is boosted by the sharpness setting."),
    Param("burst_lock", "Burst-locked color", "Goggles", "bool", True,
          help="Set the color reference from each line's color burst (as real goggles do). A noisy burst then "
               "shifts the hue of whole lines. Off = perfect reference."),
    Param("burst_lock_lines", "Color lock settling", "Goggles", "float", 40.0, 2.0, 400.0, 1.0, unit="lines",
          help="How many lines the color lock takes to swing back after the burst is knocked. Short = thin, quickly "
               "fading hue bands; long = tall bands and slow hue drift."),
    Param("pll_damping", "Color lock damping", "Goggles", "float", 0.5, 0.1, 2.0, 0.05,
          help="Low = the hue overshoots and swings back and forth after a hit (stacked bands), 1 = settles without swinging."),
    Param("pll_drift_hz", "Color oscillator error", "Goggles", "float", 60.0, -500.0, 500.0, 5.0, unit="Hz",
          advanced=True, help="How far the goggles' color crystal is off. It only shows when the lock is lost or during "
                              "vertical sync, where the hue drifts by this rate."),
    Param("acc_lines", "Color gain speed", "Goggles", "float", 20.0, 1.0, 500.0, 1.0, unit="lines",
          help="Lines the automatic color gain averages the burst size over (how fast saturation pumps)."),
    Param("acc_max_gain", "Color gain limit", "Goggles", "float", 2.5, 1.0, 8.0, 0.1, unit="x",
          help="Most the automatic color gain can boost a weak burst (how oversaturated colors can get)."),
    Param("color_killer", "Color killer", "Goggles", "bool", True,
          help="Switch color off (gray picture) when the locked burst is too weak, as goggles do."),
    Param("killer_level", "Color killer level", "Goggles", "float", 0.68, 0.0, 1.0, 0.05,
          help="Locked burst size (fraction of normal) below which color is switched off."),
    Param("hue_offset_deg", "Hue (tint)", "Goggles", "float", 0.0, -180.0, 180.0, 1.0, unit="deg",
          help="Rotate all colors around the color wheel."),
    Param("deinterlace", "Deinterlace", "Goggles", "choice", "bob", choices=("bob", "weave"),
          help="bob: each field becomes a frame (60 fps, slight vertical bounce). "
               "weave: combine two fields (combing on fast motion)."),

    # ---- Hue / saturation bands ---------------------------------------------
Param("hb_enable", "Hue bands", "Link", "bool", False, help="Flat horizontal bands where the color rotates and its saturation swells and fades (low-frequency interference on the color reference)."),
Param("hb_hue_deg", "Hue swing", "Link", "float", 80.0, 0, 180, 1, unit="deg", help="Peak hue rotation of the bands."),
Param("hb_sat_amp", "Saturation swing", "Link", "float", 0.5, 0, 1, 0.05, help="How much the bands boost or drain color (0 = hue only)."),
Param("hb_period_lines", "Band spacing", "Link", "float", 110.0, 20, 1000, 5, unit="lines", help="Lines per band cycle in one field (240 = one cycle per picture)."),
Param("hb_drift_hz", "Band drift", "Link", "float", 0.8, -30, 30, 0.1, unit="Hz", help="Bands creep up or down at this rate; 0 = frozen."),
Param("hb_shape", "Triangle share", "Link", "float", 0.3, 0, 1, 0.05, help="0 = smooth sine bands, 1 = triangle (straighter ramps, sharper turnarounds)."),
Param("hb_second_level", "Second wave", "Link", "float", 0.5, 0, 2, 0.05, advanced=True, help="Strength of a second, unrelated wave clashing with the first (uneven bands)."),
Param("hb_second_ratio", "Second wave spacing", "Link", "float", 2.7, 0.2, 10, 0.1, advanced=True, help="Its band spacing relative to the first."),
Param("hb_wander_deg", "Random hue wander", "Link", "float", 25.0, 0, 180, 1, unit="deg", advanced=True, help="Irregular extra hue drift on top of the waves."),
Param("hb_wander_lines", "Wander size", "Link", "float", 60.0, 5, 500, 5, unit="lines", advanced=True, help="Typical height of the random wander features."),
Param("hb_wander_time_s", "Wander speed", "Link", "float", 0.6, 0.05, 10, 0.05, unit="s", advanced=True, help="Seconds for the wander pattern to scroll one feature."),
Param("hb_env_s", "Come and go", "Link", "float", 0.0, 0, 20, 0.5, unit="s", advanced=True, help="Bands fade in and out over this timescale; 0 = always present."),

    # ---- Sync recovery (goggles) -------------------------------------------
    Param("sync_enable", "Sync recovery", "Sync", "bool", True,
          help="The goggles find the sync pulses themselves. Off = perfect timing (no tearing or rolling)."),
    Param("hsync_lock_lines", "Line lock speed", "Sync", "float", 6.0, 1.0, 50.0, 0.5, unit="lines",
          help="How many lines the line oscillator takes to pull back onto the sync pulses. Higher = slower "
               "recovery, longer curved tears."),
    Param("hsync_drift", "Line drift", "Sync", "float", 4.0, 0.0, 30.0, 0.1, unit="samples/line",
          help="How far the picture slides sideways per line while sync pulses are missing (14.3 samples = 1 us)."),
    Param("sync_slice_ire", "Sync slice level", "Sync", "float", -20.0, -38.0, -5.0, 0.5, unit="IRE",
          advanced=True, help="The sync separator's threshold. Closer to 0 = noise and dark dips trigger false "
                              "pulses more easily (torn lines); closer to -40 = weak pulses get missed."),
    Param("vsync_drift_lines", "Roll speed", "Sync", "float", 4.0, 0.0, 60.0, 0.5, unit="lines/field",
          help="How fast the picture rolls when the vertical sync is missed."),
    Param("vsync_lock", "Vertical lock strength", "Sync", "float", 0.7, 0.05, 1.0, 0.05, advanced=True,
          help="How much of the roll is pulled back in each field once vertical sync is found again (1 = snaps)."),

    # ---- Output -------------------------------------------------------------
    Param("upscale", "Output upscale", "Output", "int", 1, 1, 3, 1, help="Integer enlargement of the 640x480 result."),
    Param("crf", "H.264 quality (CRF)", "Output", "int", 18, 0, 51, 1, help="Lower = better quality, bigger file."),

    # ---- Run ------------------------------------------------------------------
    Param("seed", "Random seed", "Run", "int", 0, 0, 2**31 - 1, 1,
          help="Same seed gives the same noise (used by later steps)."),
]

BY_KEY = {p.key: p for p in PARAMS}
GROUPS = list(dict.fromkeys(p.group for p in PARAMS))


def defaults() -> dict:
    return {p.key: p.default for p in PARAMS}


def parse_keyframes(text: str) -> list[tuple[float, float]]:
    """'0:40, 5:40, 8:12' -> [(0.0, 40.0), (5.0, 40.0), (8.0, 12.0)] (time in seconds : value)."""
    pts = []
    for part in text.replace(";", ",").split(","):
        part = part.strip()
        if not part:
            continue
        try:
            t, v = part.split(":")
            pts.append((float(t), float(v)))
        except ValueError:
            raise ValueError(f"bad keyframe {part!r}; use time_seconds:value, for example 5:12") from None
    return sorted(pts)


def coerce(p: Param, value: Any):
    """Convert a value to the parameter's type and range-check it."""
    if p.kind == "text":
        return str(value)
    if p.kind == "bool":
        return bool(value)
    if p.kind == "choice":
        if value not in p.choices:
            raise ValueError(f"{p.key}: {value!r} not in {p.choices}")
        return value
    v = int(value) if p.kind == "int" else float(value)
    if p.min is not None and v < p.min or p.max is not None and v > p.max:
        raise ValueError(f"{p.key}: {v} outside [{p.min}, {p.max}]")
    return v


def validate(values: dict | None = None) -> dict:
    """Merge `values` over the defaults, coercing and range-checking each one."""
    out = defaults()
    for k, v in (values or {}).items():
        if k not in BY_KEY:
            raise KeyError(f"unknown parameter {k!r}")
        out[k] = coerce(BY_KEY[k], v)
    for _t, v in parse_keyframes(out["cnr_keyframes"]):
        if not -5.0 <= v <= 60.0:
            raise ValueError(f"cnr_keyframes: {v} dB outside [-5, 60]")
    if out["chroma_bp_low_mhz"] >= out["chroma_bp_high_mhz"]:
        raise ValueError("chroma_bp_low_mhz must be below chroma_bp_high_mhz")
    if out["rx_clip_low_ire"] >= out["rx_clip_high_ire"]:
        raise ValueError("rx_clip_low_ire must be below rx_clip_high_ire")
    from .modulation import parse_links
    parse_links(out["mod_links"])
    if out["hsync_len"] + 4 > 78:
        raise ValueError("hsync_len leaves no room before the color burst")
    return out


def load_preset(path_or_name: str | Path) -> dict:
    path = Path(path_or_name)
    if not path.exists():
        path = Path(__file__).resolve().parent.parent / "presets" / f"{path_or_name}.json"
    return validate(json.loads(path.read_text()))


def save_preset(values: dict, path: str | Path) -> None:
    Path(path).write_text(json.dumps(validate(values), indent=2) + "\n")
