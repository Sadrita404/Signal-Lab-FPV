# Signallab58 (SL58)

Analog FPV signal lab: turns digital video into a physically simulated analog FPV feed
(NTSC encoder -> 5.8 GHz FM link with multipath, dips, noise and fading -> goggle receiver with
sync recovery, color lock and color killer -> mp4). interflab designs interference and parameter
patches that plug into it. The Python package is still called analogfpv.

## Quick start (Windows)
    py -3.13 -m pip install numpy scipy opencv-python tkinterdnd2
    # FFmpeg + ffprobe must be on your PATH
    py -3.13 -m signallab58 gui                        # the window
    py -3.13 -m signallab58 in.mp4 out.mp4 --preset warped_bands --duration 5
    py -3.13 -m interflab gui                          # the patch editor on its own
    build_exe.bat                                      # optional: builds dist\Signallab58\Signallab58.exe

tkinterdnd2 is optional (drag and drop). Everything below is the original build log of the project.

---

# analogfpv - through step 2a: NTSC signal path + clean FM link

Digital video -> real NTSC composite signal (4x subcarrier, 910 samples/line, sync, burst,
interlaced fields) -> FM radio link (complex baseband) -> goggle-style decoder -> mp4. No noise or
interference yet; this is the clean baseline the later steps (FM link, snow, goggle sync, channel effects, diversity) build on.

## Setup
    pip install numpy scipy opencv-python
    # FFmpeg + ffprobe must be on your PATH

## Use
    python -m analogfpv input.mp4 output.mp4
    python -m analogfpv input.mp4 output.mp4 --preset soft_analog --comb-amount 0.5
    python -m analogfpv input.mp4 output.mp4 --start 5 --duration 10
    python -m analogfpv --list-params
    python tests/selftest.py

## Layout
    analogfpv/params.py    every setting, declared once (CLI, presets and a future GUI all read this)
    analogfpv/ntsc.py      signal constants, encode_field(), decode_field()
    analogfpv/pipeline.py  Pipeline.process_frame(), process_still(), render_preview(), process_video()
    analogfpv/link.py      FM modulate / receiver filter / demodulate; AIR_STAGES hook for noise etc.
    analogfpv/video_io.py  FFmpeg pipes in and out
    analogfpv/cli.py       command line, flags generated from the schema
    presets/*.json         parameter sets

## Snow (step 2b)
--link-cnr-db sets signal strength: ~25 faint grain, ~18 light, ~14 visible, ~11 heavy, below ~9 sparkles.
--no-noise-enable turns the noise off. Noise is calibrated over --noise-ref-bw-mhz (advanced).

## Signal strength over time (step 2c-1)
--cnr-keyframes "0:40, 5:40, 8:12, 12:8, 14:40" sets signal strength (dB) along the clip, straight lines between
points (seconds from the start of the processed part). Empty = constant --link-cnr-db.

## Random fading (step 2c-2)
--fade-enable adds random wobble on top of the signal strength; --fade-k-db (high = gentle, low = deep dropouts)
and --fade-rate-hz (speed) shape it. It shows up through the noise, so it needs noise on.

## Burst-locked color (step 2d-1)
--burst-lock (default) sets the color reference from each line's burst, so noise on the burst shifts the hue
of whole lines. --burst-lock-lines (1 = hue stripes, higher = slow drift) and --hue-offset-deg (tint).

## White-to-color glitch
--fm-white-glitch (default) lets a too-narrow receiver filter turn bright areas into colored patches;
--no-fm-white-glitch caps the FM swing so whites stay clean. --fm-fit-ratio (advanced) sets the threshold.

## interflab interference (step 3a)
--if2-enable adds an interflab patch to the received video signal right before the goggles' decoder, so the
decoder's own burst lock and color demodulation make the bands. --if2-patch takes a .json path or a name from
patches/ (default tone_burst). --if2-scale-ire sets strength (20 = patch value 1 is burst-sized). Try it with
--burst-lock-lines 1 for sharp bands. The interflab package now ships in this folder next to analogfpv.

## interflab patch editor (step 4a)
    py -3.13 -m interflab gui                      # opens with the tone_burst example
    py -3.13 -m interflab gui patches/slow_push.json
Left: sources (max 8) and cables. Middle: the selected source; sliders come from SOURCE_SCHEMA, type exact
values in the boxes (Enter). A * next to a setting means a cable drives it. Right: scope (one field, line
level over time, spectrum, two lines), redrawn after each change. Save the patch as .json and use it with
analogfpv --if2-enable --if2-patch yourpatch.json. tkinter comes with the normal Windows Python install.

## Goggle input clipping (step 4b)
--rx-clip-enable (default on) cuts the received signal to the goggles' input range, --rx-clip-high-ire 125 and
--rx-clip-low-ire -45. A strong push (for example slow_push with --if2-scale-ire 80) then drives the picture into
the limit and the color riding on it is flattened too: bright pushes wash out, dark pushes lose color.

## Multipath (step 5a)
--mp-enable adds reflections on the radio link: --mp-paths (1-4 echoes), --mp-level-db (strongest echo, 0 = as
strong as the direct signal), --mp-delay-ns (how late), --mp-doppler-hz (how fast they drift in and out of phase).
Echoes give ghosts and smeared edges; where they cancel, snow and color errors come in rolling bands. Works best
together with noise (lower --link-cnr-db) and the goggle input clip.

## Real color lock, color gain, color killer + DirtyFPV defaults (step 5b)
The goggles' color reference is now a phase-locked loop on the burst: knocked by a damaged burst it swings back
over --burst-lock-lines (default 40) with --pll-damping (0.5 = some overshoot), and free-runs during vertical sync
on --pll-drift-hz. Automatic color gain (--acc-lines, --acc-max-gain) scales chroma by burst size, so the same
hit changes hue AND saturation. --color-killer turns a field gray when lock quality falls below --killer-level.
Defaults are tuned on DirtyFPV.mp4: CNR 25 dB with fading (K 6 dB, 3 Hz) and multipath (2 echoes, 100 ns,
-4 dB, 25 Hz). Hue bands and flicker now come from reflections making the color phase depend on brightness.
--preset clean gives the old clean link.

## Speed
About 11 s of processing per second of video (the FM stage is the slow part). Use --duration for tests,
or --no-fm-enable to skip the radio stage.

## Where later steps plug in
    link.AIR_STAGES           functions (x, fs, ctx, params, state) -> x on the radio signal: noise, fading, interference
    Pipeline.channel_stages   functions (signal, ctx, params, state) -> signal, run between encode and decode
    decode_field(line_starts) timing hook for the goggle sync-recovery step
