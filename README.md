

# Signallab58 (SL58)

Run clean digital video through a simulation of the analog FPV chain and get back a convincingly grungy MP4.

Signallab58 models the whole path, stage by stage:

1. NTSC encode (composite signal, subcarrier, burst, interlaced fields)
2. FM link (5.8 GHz style modulation, receiver filtering, noise, fading)
3. Air interference (multipath, dips, patterns you design yourself)
4. Receiver decode, including color PLL, ACC and the color killer
5. Sync recovery (horizontal and vertical, with the tearing and rolling that goes with it)
6. MP4 export through FFmpeg

## About this project

- It was vibecoded with Claude. Expect it to behave like a project built that way.
- I use it to test and train my other project, DVR Doctor, which cleans up exactly this kind of look.
- It looks really cool, so I'm releasing it for free for anyone who wants to have fun with it.
- It was tuned against Skyzone Cobra X V4 goggle footage. Other goggles will look different, and the defaults will not match them.
- There are rough edges. Issues and pull requests are welcome.

## What is in the box

| Part | What it does |
| --- | --- |
| Main app | The pipeline, a command line and a GUI. |
| interflab | A patch editor for designing interference patterns, saved as JSON. Sources can be Interfere or Parameter. Draggable dots link a pattern onto the settings. |
| Presets | Ready-made parameter sets in `presets/`, such as `warped_bands.json` and `static_dips.json`. |
| Windows exe (optional) | `build_exe.bat` builds a standalone `Signallab58.exe` with PyInstaller. |

## Requirements

- Python 3.13 (the commands below use the Windows `py` launcher)
- numpy, scipy, opencv-python
- FFmpeg and ffprobe on your PATH
- tkinterdnd2, optional, for drag and drop in the GUI

```
py -3.13 -m pip install numpy scipy opencv-python tkinterdnd2
```

## Usage

Command line:

```
py -3.13 -m signallab58 "in.mp4" out.mp4 --duration 5
```

Useful flags:

```
py -3.13 -m signallab58 "in.mp4" out.mp4 --preset warped_bands --start 5 --duration 10
py -3.13 -m signallab58 --list-params
```

GUI:

```
py -3.13 -m signallab58 gui
```

Interference designer on its own:

```
py -3.13 -m interflab gui
```

interflab also has `list`, `example`, `plot` and `render` subcommands for working with patches from the terminal.

## Presets

Presets live in `presets/` as JSON. Two good places to start:

- `warped_bands.json`
- `static_dips.json`

## Building the Windows exe

Optional. Run `build_exe.bat` from the folder that holds `analogfpv`, `interflab`, `presets` and `patches`. It installs PyInstaller, builds `dist\Signallab58\Signallab58.exe` and copies `ffmpeg` and `ffprobe` next to it if it finds them on your PATH. If it does not, drop them into that folder yourself. Share the whole `dist\Signallab58` folder as a zip.

## Contributing

Issues and pull requests are welcome, especially footage comparisons from other goggles and receivers.

## License

MIT. See Licence.

---

Tell me which license you want and I'll fill it in.
