# `ctk shoot`

Deterministic screenshots, so an agent can **look at** the UI it changed, and
compare it with a baseline instead of guessing. Image work (PNG decoding,
diffs, contact sheets) is pure standard library.

```bash
ctk shoot web localhost:5173                          # a dev server, file or URL
ctk shoot web app.html --size 390x844 --dark --full-page
ctk shoot web localhost:3000/login --wait-for "#form" --mask-selector ".clock"
ctk shoot godot ~/games/demo --scene res://ui/menu.tscn --frames 120
ctk shoot desktop --size 1024x768 --delay 3 -- ./build/my-gtk-app
ctk shoot compare baseline.png actual.png --mask 0,0,200,40
ctk shoot sheet before.png after.png diff.png -o sheet.png
```

Every capture prints one line with the source, size, duration and file path
(by default `~/.cache/claude-toolkit/shoot/<timestamp>-<kind>.png`, the
newest 200 kept). Claude Code can then read the PNG.

## Capture backends

| Kind | How | Determinism |
|---|---|---|
| `web` | Playwright's Chromium via `uv run --with playwright==1.63.0` (nothing is installed into the project) | fixed viewport and scale, UTC, `en-US`, `prefers-reduced-motion`, CSS animations/transitions and the caret frozen, waits for network idle and web fonts; `--mask-selector` paints elements magenta |
| `godot` | Godot 4's movie writer: `--fixed-fps 60 --write-movie`, runs `--frames` frames and keeps the last one | fixed time step, audio disabled; `--size` sets the viewport through a temporary `override.cfg` (refused if the project already has one) |
| `desktop` | the program on a private `Xvfb` display, grabbed with ImageMagick `import` or ffmpeg after `--delay` seconds | clean screen of the requested size, nothing else running on it; the program's process group is stopped afterwards |

`godot` also runs on Xvfb when it is installed, so no window appears; otherwise
it uses the current display. Prefer Xvfb: on a desktop session the compositor's
scaling (HiDPI) and GPU change the rendering, so a baseline only matches
captures made in the same environment. Install Xvfb and create baselines with
it, locally and in CI alike. Web captures report HTTP errors, console errors
and uncaught page errors as `note:` lines.

## Baselines

Add `--baseline path.png` to any capture:

- the first run creates the baseline (exit `0`);
- later runs compare with it: a pixel differs when any channel changes by
  more than `--threshold` (default `8` of 255); the capture matches when at
  most `--tolerance` percent of the compared pixels differ (default `0.1`);
- `--mask x,y,w,h` (repeatable) leaves rectangles out of the comparison;
- on a difference the command exits `1` and prints the percentage, the pixel
  count, the bounding box of the change and a diff image (`<shot>-diff.png`:
  the capture faded to grey, changes in red, masks in blue);
- `--update` replaces the baseline.

```
shoot: differs from baseline ~/app/shots/home.png: 3.29% (30,321 px, tolerance 0.1%) · box x=40 y=91 w=348 h=178 · diff: ~/.cache/claude-toolkit/shoot/20261013-114902-web-diff.png
```

`ctk shoot compare <baseline> <actual>` does the same for two existing files.

## Contact sheets

`ctk shoot sheet a.png b.png …` lays thumbnails out in a grid (`--columns`,
`--thumb-width`), numbered in the order given, and prints the legend. One
image is cheaper for an agent to read than several.

## Exit codes

| Code | Meaning |
|---|---|
| `0` | captured; baseline created, updated or matched |
| `1` | differs from the baseline, or the capture failed (the reason is on stderr) |
| `3` | Playwright's Chromium must be downloaded and no terminal is attached; rerun with `--yes` after approval |

## Requirements

`web` needs `uv`; the first run without the browser asks before downloading
Chromium (~150 MB into `~/.cache/ms-playwright`). `godot` needs Godot 4 on
`PATH` (`godot` or `godot4`). `desktop` needs `Xvfb` and ImageMagick or
ffmpeg. `ctk doctor --toolkit` lists what is missing.

## Done criteria (tested in `tests/test_shoot.py`)

- The PNG decoder reads every colour type and bit depth used by browsers,
  Godot, ImageMagick and ffmpeg, matching ImageMagick pixel for pixel.
- Comparison counts exactly the changed pixels with their bounding box;
  `--threshold` ignores noise, masks exclude regions, size changes never pass.
- A baseline is created, matched, reported as different with a diff image, and updated.
- A missing browser needs confirmation (exit `3` without a terminal).
- Godot keeps the last frame, honours `--size` without leaving files behind
  and reports script errors.
- A program on a private Xvfb display is captured at the requested size.
- Two captures of an animated page with a masked clock, or of a moving Godot
  scene on Xvfb, match at 0.00% (checked by hand; Chromium and Godot are not in CI).
