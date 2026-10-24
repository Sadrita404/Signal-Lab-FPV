# Signallab58 setup guide

This guide shows the exact terminal commands to install the required dependencies and run the program from a fresh macOS terminal session.

## 1) Open Terminal

## 2) Go to the project folder

```bash
cd /Users/sadritaneogi/Desktop/signalab58-main/signalab58
```

## 3) Create and activate a virtual environment (recommended)

```bash
python3 -m venv .venv
source .venv/bin/activate
```

## 4) Upgrade pip

```bash
python -m pip install --upgrade pip
```

## 5) Install the app dependencies

```bash
python -m pip install numpy scipy opencv-python tkinterdnd2
```

## 6) Install FFmpeg and ffprobe if they are not already available

On macOS with Homebrew:

```bash
brew install ffmpeg
```

Then verify they are on your PATH:

```bash
ffmpeg -version
ffprobe -version
```

## 7) Launch the GUI

```bash
python -m signallab58 gui
```

## 8) Optional: run a sample CLI render

```bash
python -m signallab58 /path/to/input.mp4 /path/to/output.mp4 --preset warped_bands --duration 5
```

Example with a local file:

```bash
python -m signallab58 input.mp4 output.mp4 --preset warped_bands --duration 5
```

## 9) Optional: list available presets

```bash
python -m signallab58 --list-params
```

## 10) Optional: run the interference patch editor

```bash
python -m interflab gui
```

## Notes

- Run all commands from inside `/Users/sadritaneogi/Desktop/signalab58-main/signalab58`.
- The package is structured under that folder, so `python -m signallab58 ...` works only there.
- If `python -m signallab58 gui` fails because the module is not found, make sure you are in the correct folder and the virtual environment is active.
