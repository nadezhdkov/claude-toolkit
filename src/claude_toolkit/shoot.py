"""``ctk shoot``: deterministic screenshots, baseline comparison and contact sheets.

Capture backends:
- ``web``: Playwright's Chromium, run through ``uv run --with playwright``
  (fixed viewport, UTC, en-US, reduced motion, animations and caret frozen);
- ``godot``: Godot 4's movie writer at a fixed frame rate, last frame kept;
- ``desktop``: any program on a private Xvfb display.

``--baseline`` compares a capture with a reference image (created on first
use), with a per-channel threshold, a tolerance and masked rectangles; a diff
image highlights what changed. Image work is pure standard library (``png``).
"""

from __future__ import annotations

import contextlib
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import tempfile
import time
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path

from . import png
from .common import confirm, parse_version, run_text
from .style import Spinner, Style, shorten_home

PLAYWRIGHT = "playwright==1.63.0"
KEEP_SHOTS = 200
DEFAULT_SIZE = (1280, 720)
EXIT_DIFFERS = 1


class ShootError(Exception):
    """A capture could not be made; the message says why and what to do."""


class BrowserMissing(ShootError):
    """Playwright runs but its Chromium has not been downloaded."""


def shot_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "claude-toolkit" / "shoot"


def default_output(kind: str) -> Path:
    directory = shot_dir()
    directory.mkdir(parents=True, exist_ok=True)
    shots = sorted(directory.glob("*.png"), key=lambda path: path.stat().st_mtime, reverse=True)
    for old in shots[KEEP_SHOTS:]:
        old.unlink(missing_ok=True)
    return directory / f"{time.strftime('%Y%m%d-%H%M%S')}-{kind}.png"


def parse_size(text: str) -> tuple[int, int]:
    match = re.fullmatch(r"(\d+)[xX](\d+)", text.strip())
    if not match or not all(0 < int(value) <= 16384 for value in match.groups()):
        raise ValueError(f"size must look like 1280x720, got {text!r}")
    return int(match.group(1)), int(match.group(2))


@dataclass(frozen=True)
class Rect:
    x: int
    y: int
    w: int
    h: int

    @classmethod
    def parse(cls, text: str) -> Rect:
        parts = [part.strip() for part in text.split(",")]
        if len(parts) != 4 or not all(part.isdigit() for part in parts):
            raise ValueError(f"mask must be x,y,width,height in pixels, got {text!r}")
        return cls(*(int(part) for part in parts))

    def contains(self, x: int, y: int) -> bool:
        return self.x <= x < self.x + self.w and self.y <= y < self.y + self.h


@dataclass
class Capture:
    path: Path
    source: str
    width: int
    height: int
    seconds: float
    notes: list[str] = field(default_factory=list)


# --- Comparison --------------------------------------------------------------------


@dataclass
class Comparison:
    width: int
    height: int
    differing: int
    compared: int
    box: Rect | None
    size_mismatch: str | None = None
    diff_path: Path | None = None

    @property
    def ratio(self) -> float:
        return self.differing / self.compared if self.compared else 0.0

    def passes(self, tolerance_percent: float) -> bool:
        return self.size_mismatch is None and self.ratio * 100 <= tolerance_percent


def _masked_rows(masks: list[Rect], width: int, height: int) -> dict[int, list[Rect]]:
    rows: dict[int, list[Rect]] = {}
    for mask in masks:
        for y in range(max(0, mask.y), min(height, mask.y + mask.h)):
            rows.setdefault(y, []).append(mask)
    return rows


def compare(
    baseline: png.Image, actual: png.Image, *, threshold: int = 8, masks: list[Rect] | None = None
) -> tuple[Comparison, png.Image | None]:
    """Count pixels whose largest channel difference exceeds ``threshold``, outside ``masks``."""
    masks = masks or []
    if (baseline.width, baseline.height) != (actual.width, actual.height):
        mismatch = f"size {actual.width}x{actual.height} differs from baseline {baseline.width}x{baseline.height}"
        return Comparison(actual.width, actual.height, 0, 0, None, mismatch), None
    width, height = actual.width, actual.height
    masked = _masked_rows(masks, width, height)
    masked_pixels = sum(
        sum(1 for x in range(width) if any(rect.contains(x, y) for rect in rects)) for y, rects in masked.items()
    )
    stride = width * 4
    a, b = baseline.rgba, actual.rgba
    differing_pixels: list[int] = []
    for y in range(height):
        start = y * stride
        if a[start : start + stride] == b[start : start + stride]:
            continue
        rects = masked.get(y, ())
        for x in range(width):
            i = start + x * 4
            if a[i : i + 4] == b[i : i + 4] or (rects and any(rect.contains(x, y) for rect in rects)):
                continue
            delta = max(abs(a[i] - b[i]), abs(a[i + 1] - b[i + 1]), abs(a[i + 2] - b[i + 2]), abs(a[i + 3] - b[i + 3]))
            if delta > threshold:
                differing_pixels.append(y * width + x)
    box = None
    if differing_pixels:
        xs = [index % width for index in differing_pixels]
        ys = [index // width for index in differing_pixels]
        box = Rect(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)
    result = Comparison(width, height, len(differing_pixels), width * height - masked_pixels, box)
    return result, (_diff_image(actual, differing_pixels, masked) if differing_pixels else None)


def _diff_image(actual: png.Image, differing: list[int], masked: dict[int, list[Rect]]) -> png.Image:
    """The capture faded to grey, differing pixels in red, masked areas tinted blue."""
    rgba = actual.rgba
    grey = bytearray(len(rgba))
    lum = bytes(
        180 + (r * 3 + g * 6 + b) // 10 * 75 // 255 for r, g, b in zip(rgba[0::4], rgba[1::4], rgba[2::4], strict=True)
    )
    grey[0::4] = grey[1::4] = grey[2::4] = lum
    grey[3::4] = b"\xff" * (len(rgba) // 4)
    width = actual.width
    for y, rects in masked.items():
        for x in range(width):
            if any(rect.contains(x, y) for rect in rects):
                i = (y * width + x) * 4
                grey[i : i + 3] = bytes((grey[i] * 2 // 3, grey[i + 1] * 2 // 3, 255))
    for index in differing:
        grey[index * 4 : index * 4 + 4] = b"\xe0\x10\x30\xff"
    return png.Image(width, actual.height, grey)


@dataclass
class BaselineResult:
    status: str  # created, updated, matches, differs
    comparison: Comparison | None = None


def check_baseline(
    shot: Path,
    baseline: Path,
    *,
    update: bool = False,
    threshold: int = 8,
    tolerance: float = 0.1,
    masks: list[Rect] | None = None,
    diff_path: Path | None = None,
) -> BaselineResult:
    if update or not baseline.exists():
        baseline.parent.mkdir(parents=True, exist_ok=True)
        status = "updated" if baseline.exists() else "created"
        shutil.copyfile(shot, baseline)
        return BaselineResult(status)
    comparison, diff = compare(png.read(baseline), png.read(shot), threshold=threshold, masks=masks)
    if diff is not None and not comparison.passes(tolerance):
        comparison.diff_path = png.write(diff, diff_path or shot.with_name(shot.stem + "-diff.png"))
    return BaselineResult("matches" if comparison.passes(tolerance) else "differs", comparison)


# --- Contact sheet --------------------------------------------------------------------

# 3x5 digits for labelling thumbnails without a font.
DIGITS = {
    "0": "111101101101111", "1": "010110010010111", "2": "111001111100111", "3": "111001111001111",
    "4": "101101111001001", "5": "111100111001111", "6": "111100111101111", "7": "111001001001001",
    "8": "111101111101111", "9": "111101111001111",
}  # fmt: skip


def thumbnail(image: png.Image, width: int) -> png.Image:
    """Downscale to ``width`` (never up) by averaging a 2x2 sample per output pixel."""
    if image.width <= width:
        return image
    height = max(1, round(image.height * width / image.width))
    src, sw = image.rgba, image.width
    out = bytearray(width * height * 4)
    step_x, step_y = image.width / width, image.height / height
    for y in range(height):
        y0 = int(y * step_y)
        y1 = min(image.height - 1, int((y + 0.5) * step_y))
        for x in range(width):
            x0 = int(x * step_x)
            x1 = min(sw - 1, int((x + 0.5) * step_x))
            a, b = (y0 * sw + x0) * 4, (y0 * sw + x1) * 4
            c, d = (y1 * sw + x0) * 4, (y1 * sw + x1) * 4
            o = (y * width + x) * 4
            for k in range(4):
                out[o + k] = (src[a + k] + src[b + k] + src[c + k] + src[d + k]) // 4
    return png.Image(width, height, out)


def _paste(canvas: png.Image, image: png.Image, left: int, top: int) -> None:
    stride = image.width * 4
    for y in range(image.height):
        start = ((top + y) * canvas.width + left) * 4
        canvas.rgba[start : start + stride] = image.rgba[y * stride : (y + 1) * stride]


def _label(canvas: png.Image, text: str, left: int, top: int, scale: int = 3) -> None:
    box_w, box_h = (len(text) * 4 + 1) * scale, 7 * scale
    for y in range(top, min(canvas.height, top + box_h)):
        for x in range(left, min(canvas.width, left + box_w)):
            i = (y * canvas.width + x) * 4
            canvas.rgba[i : i + 4] = b"\x0f\x17\x2a\xff"
    for n, char in enumerate(text):
        bits = DIGITS[char]
        for row in range(5):
            for col in range(3):
                if bits[row * 3 + col] == "1":
                    for dy in range(scale):
                        for dx in range(scale):
                            x = left + (1 + n * 4 + col) * scale + dx
                            y = top + (1 + row) * scale + dy
                            if x < canvas.width and y < canvas.height:
                                i = (y * canvas.width + x) * 4
                                canvas.rgba[i : i + 4] = b"\x38\xbd\xf8\xff"


def contact_sheet(paths: list[Path], *, columns: int = 3, thumb_width: int = 400, gap: int = 8) -> png.Image:
    thumbs = [thumbnail(png.read(path), thumb_width) for path in paths]
    columns = max(1, min(columns, len(thumbs)))
    rows = (len(thumbs) + columns - 1) // columns
    cell_w = max(t.width for t in thumbs)
    row_heights = [max(t.height for t in thumbs[r * columns : (r + 1) * columns]) for r in range(rows)]
    width = columns * cell_w + (columns + 1) * gap
    height = sum(row_heights) + (rows + 1) * gap
    sheet = png.Image.blank(width, height, (30, 41, 59, 255))
    top = gap
    for r in range(rows):
        for c, thumb in enumerate(thumbs[r * columns : (r + 1) * columns]):
            left = gap + c * (cell_w + gap)
            _paste(sheet, thumb, left, top)
            _label(sheet, str(r * columns + c + 1), left, top)
        top += row_heights[r] + gap
    return sheet


# --- Capture backends -------------------------------------------------------------------


def _free_display() -> int:
    for number in range(99, 199):
        if not Path(f"/tmp/.X11-unix/X{number}").exists() and not Path(f"/tmp/.X{number}-lock").exists():
            return number
    raise ShootError("no free X display number between :99 and :198")


@contextlib.contextmanager
def virtual_display(size: tuple[int, int]) -> Iterator[str]:
    """A private Xvfb display (``:N``) for the duration of the block."""
    xvfb = shutil.which("Xvfb")
    if not xvfb:
        raise ShootError("Xvfb is not installed (see `ctk doctor --toolkit` for the install command)")
    display = f":{_free_display()}"
    process = subprocess.Popen(
        [xvfb, display, "-screen", "0", f"{size[0]}x{size[1]}x24", "-nolisten", "tcp", "-noreset"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        socket = Path(f"/tmp/.X11-unix/X{display[1:]}")
        deadline = time.monotonic() + 10
        while not socket.exists():
            if process.poll() is not None or time.monotonic() > deadline:
                raise ShootError(f"Xvfb did not start on {display}")
            time.sleep(0.05)
        yield display
    finally:
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()


def _grab_display(display: str, size: tuple[int, int], out: Path) -> None:
    if shutil.which("magick"):
        command = ["magick", "import", "-display", display, "-window", "root", f"png:{out}"]
    elif shutil.which("import"):
        command = ["import", "-display", display, "-window", "root", f"png:{out}"]
    elif shutil.which("ffmpeg"):
        command = ["ffmpeg", "-loglevel", "error", "-y", "-f", "x11grab", "-video_size", f"{size[0]}x{size[1]}"]
        command += ["-i", display, "-frames:v", "1", str(out)]
    else:
        raise ShootError("capturing a display needs ImageMagick (`import`) or ffmpeg")
    done = subprocess.run(
        command, capture_output=True, text=True, timeout=30, check=False, encoding="utf-8", errors="replace"
    )
    if done.returncode != 0 or not out.exists():
        raise ShootError(f"screen grab failed: {(done.stderr or done.stdout).strip()[:300]}")


def _stop_group(process: subprocess.Popen) -> None:
    with contextlib.suppress(ProcessLookupError, PermissionError):
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        with contextlib.suppress(ProcessLookupError, PermissionError):
            os.killpg(process.pid, signal.SIGKILL)
        process.wait(timeout=5)


def capture_desktop(command: list[str], out: Path, *, size: tuple[int, int], delay: float) -> Capture:
    if not command:
        raise ShootError("usage: ctk shoot desktop [options] -- <command> [args...]")
    if not shutil.which(command[0]):
        raise ShootError(f"command not found: {command[0]}")
    started = time.monotonic()
    with virtual_display(size) as display:
        env = {**os.environ, "DISPLAY": display}
        env.pop("WAYLAND_DISPLAY", None)
        process = subprocess.Popen(
            command, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, start_new_session=True
        )
        try:
            time.sleep(delay)
            exited = process.poll()
            _grab_display(display, size, out)
        finally:
            _stop_group(process)
    notes = [f"the program exited with code {exited} before the capture"] if exited is not None else []
    return Capture(out, " ".join(command), *size, time.monotonic() - started, notes)


def godot_binary() -> str | None:
    for name in ("godot4", "godot"):
        path = shutil.which(name)
        if path:
            version = parse_version(run_text([path, "--version"]))
            if version and version[0] >= 4:
                return path
    return None


def _has_display() -> bool:
    return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))


@contextlib.contextmanager
def _viewport_override(project: Path, size: tuple[int, int] | None) -> Iterator[None]:
    """Godot's movie writer uses the project's viewport size, so ``--size`` goes through a temporary override.cfg."""
    if size is None:
        yield
        return
    override = project / "override.cfg"
    if override.exists():
        raise ShootError(f"{override} already exists; drop --size to use the project's own size")
    override.write_text(
        f"[display]\n\nwindow/size/viewport_width={size[0]}\nwindow/size/viewport_height={size[1]}\n", encoding="utf-8"
    )
    try:
        yield
    finally:
        override.unlink(missing_ok=True)


def capture_godot(
    project: Path,
    out: Path,
    *,
    scene: str | None,
    size: tuple[int, int] | None,
    frames: int,
    timeout: float = 120,
) -> Capture:
    if not (project / "project.godot").is_file():
        raise ShootError(f"not a Godot project (no project.godot): {project}")
    godot = godot_binary()
    if not godot:
        raise ShootError("Godot 4 is not installed (`godot` or `godot4` on PATH)")
    started = time.monotonic()
    with tempfile.TemporaryDirectory(prefix="ctk-shoot-") as tmp:
        frame = Path(tmp) / "frame.png"
        command = [godot, "--path", str(project), "--fixed-fps", "60"]
        command += ["--disable-vsync", "--audio-driver", "Dummy", "--write-movie", str(frame)]
        command += ["--quit-after", str(frames)]
        if scene:
            command.append(scene)
        with contextlib.ExitStack() as stack:
            stack.enter_context(_viewport_override(project, size))
            env = dict(os.environ)
            if not _has_display() or shutil.which("Xvfb"):
                env["DISPLAY"] = stack.enter_context(virtual_display(size or (1920, 1080)))
                env.pop("WAYLAND_DISPLAY", None)
            try:
                done = subprocess.run(
                    command,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=timeout,
                    check=False,
                    encoding="utf-8",
                    errors="replace",
                )
            except subprocess.TimeoutExpired as expired:
                raise ShootError(f"Godot did not quit within {timeout:g}s") from expired
        written = sorted(Path(tmp).glob("frame*.png"))
        if not written:
            detail = "\n".join((done.stderr or done.stdout).strip().splitlines()[-5:])
            raise ShootError(f"Godot wrote no frames (exit {done.returncode})\n{detail}")
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(written[-1], out)
    errors = [line for line in (done.stderr or "").splitlines() if line.startswith(("ERROR", "SCRIPT ERROR"))]
    notes = [f"{len(errors)} Godot error line(s), first: {errors[0][:200]}"] if errors else []
    image = png.read(out)
    return Capture(
        out, f"{project} {scene or '(main scene)'}", image.width, image.height, time.monotonic() - started, notes
    )


def _web_target(target: str) -> str:
    if re.match(r"^[a-z][a-z0-9+.-]*://", target) or target.startswith(("about:", "data:")):
        return target
    path = Path(target).expanduser()
    if path.exists():
        return path.resolve().as_uri()
    return "http://" + target if re.match(r"^(localhost|127\.|\[::1\]|[\w.-]+:\d+)", target) else target


def _run_web(options: dict) -> subprocess.CompletedProcess:
    uv = shutil.which("uv")
    if not uv:
        raise ShootError("uv is required to run Playwright (see `ctk doctor --toolkit`)")
    script = Path(__file__).with_name("shoot_web.py")
    command = [uv, "run", "--no-project", "--quiet", "--with", PLAYWRIGHT, "python", "-I", str(script)]
    return subprocess.run(
        [*command, json.dumps(options)],
        capture_output=True,
        text=True,
        timeout=options["timeout"] + 120,
        check=False,
        encoding="utf-8",
        errors="replace",
    )


def install_browser(*, assume_yes: bool) -> bool:
    question = f"Playwright's Chromium is missing. Download it (~150 MB, into ~/.cache/ms-playwright) with {PLAYWRIGHT}"
    if not confirm(question + "?", assume_yes=assume_yes):
        return False
    uv = shutil.which("uv") or "uv"
    done = subprocess.run(
        [uv, "run", "--no-project", "--quiet", "--with", PLAYWRIGHT, "playwright", "install", "chromium"], check=False
    )
    return done.returncode == 0


def capture_web(
    target: str,
    out: Path,
    *,
    size: tuple[int, int],
    scale: float = 1,
    full_page: bool = False,
    wait_for: str | None = None,
    delay_ms: int = 0,
    mask_selectors: list[str] | None = None,
    dark: bool = False,
    timeout: float = 30,
) -> Capture:
    url = _web_target(target)
    options = {
        "url": url,
        "out": str(out),
        "width": size[0],
        "height": size[1],
        "scale": scale,
        "full_page": full_page,
        "wait_for": wait_for,
        "delay": delay_ms,
        "mask_selectors": mask_selectors or [],
        "color_scheme": "dark" if dark else "light",
        "timeout": timeout,
    }
    out.parent.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    done = _run_web(options)
    if done.returncode == 10:
        raise BrowserMissing("Playwright's Chromium is not installed")
    result: dict = {}
    with contextlib.suppress(json.JSONDecodeError, IndexError):
        result = json.loads(done.stdout.strip().splitlines()[-1])
    if done.returncode != 0 or not out.exists():
        reason = result.get("error") or "\n".join((done.stderr or done.stdout).strip().splitlines()[-5:])
        raise ShootError(f"browser capture failed: {reason}")
    notes = []
    if result.get("status") and result["status"] >= 400:
        notes.append(f"HTTP {result['status']}")
    for key, label in (("page_errors", "page error"), ("console_errors", "console error")):
        messages = result.get(key) or []
        if messages:
            notes.append(f"{len(messages)} {label}(s), first: {messages[0]}")
    image = png.read(out)
    return Capture(out, url, image.width, image.height, time.monotonic() - started, notes)


# --- Output -------------------------------------------------------------------------------


def _percent(ratio: float) -> str:
    return f"{ratio * 100:.2f}%"


def render_capture(capture: Capture, kind: str, st: Style | None = None) -> str:
    st = st or Style.detect()
    where = shorten_home(capture.path)
    facts = f"{capture.width}x{capture.height} · {capture.seconds:.1f}s"
    if not st.enabled:
        lines = [f"shoot: {kind} {capture.source} · {facts} → {where}"]
        lines += [f"  note: {note}" for note in capture.notes]
        return "\n".join(lines)
    lines = [st.header("ctk shoot", f"{kind} {capture.source}"), ""]
    lines.append(f"  {st.ok('✓ captured', bold=True)} {st.muted('· ' + facts)}")
    lines.append(f"  {st.muted('file')} {st.accent2(where)}")
    lines += [f"  {st.warn('!', bold=True)} {note}" for note in capture.notes]
    return "\n".join(lines)


def render_baseline(result: BaselineResult, baseline: Path, tolerance: float, st: Style | None = None) -> str:
    st = st or Style.detect()
    where = shorten_home(baseline)
    comparison = result.comparison
    if result.status in ("created", "updated"):
        text = f"baseline {result.status}: {where}"
        return f"  {st.ok('✓ ' + text)}" if st.enabled else f"shoot: {text}"
    assert comparison is not None
    if comparison.size_mismatch:
        text = f"differs from baseline {where}: {comparison.size_mismatch}"
        return f"  {st.err('✗ ' + text, bold=True)}" if st.enabled else f"shoot: {text}"
    detail = f"{_percent(comparison.ratio)} ({comparison.differing:,} px, tolerance {tolerance:g}%)"
    if result.status == "matches":
        text = f"matches baseline {where}: {detail}"
        return f"  {st.ok('✓ ' + text)}" if st.enabled else f"shoot: {text}"
    box = comparison.box
    parts = [f"differs from baseline {where}: {detail}"]
    if box:
        parts.append(f"box x={box.x} y={box.y} w={box.w} h={box.h}")
    if comparison.diff_path:
        parts.append(f"diff: {shorten_home(comparison.diff_path)}")
    if st.enabled:
        return f"  {st.err('✗ ' + parts[0], bold=True)}\n" + "\n".join(f"    {st.muted(part)}" for part in parts[1:])
    return "shoot: " + " · ".join(parts)


# --- Command ----------------------------------------------------------------------------------


def _baseline_step(args, shot: Path, masks: list[Rect]) -> int:
    if not args.baseline:
        return 0
    baseline = Path(args.baseline).expanduser()
    result = check_baseline(
        shot, baseline, update=args.update, threshold=args.threshold, tolerance=args.tolerance, masks=masks
    )
    print(render_baseline(result, baseline, args.tolerance))
    return EXIT_DIFFERS if result.status == "differs" else 0


def _capture(args, out: Path, size: tuple[int, int] | None) -> Capture:
    with Spinner(f"capturing {args.kind}"):
        if args.kind == "web":
            return capture_web(
                args.target,
                out,
                size=size or DEFAULT_SIZE,
                scale=args.scale,
                full_page=args.full_page,
                wait_for=args.wait_for,
                delay_ms=args.delay,
                mask_selectors=args.mask_selector,
                dark=args.dark,
                timeout=args.timeout,
            )
        if args.kind == "godot":
            project = Path(args.project).expanduser().resolve()
            return capture_godot(project, out, scene=args.scene, size=size, frames=args.frames)
        command = args.command[1:] if args.command[:1] == ["--"] else args.command
        return capture_desktop(command, out, size=size or DEFAULT_SIZE, delay=args.delay)


def run(args) -> int:
    try:
        masks = [Rect.parse(text) for text in getattr(args, "mask", None) or []]
        if args.kind == "compare":
            return run_compare(args, masks)
        if args.kind == "sheet":
            paths = [Path(path).expanduser() for path in args.images]
            out = Path(args.output).expanduser() if args.output else default_output("sheet")
            png.write(contact_sheet(paths, columns=args.columns, thumb_width=args.thumb_width), out)
            print(f"shoot: contact sheet of {len(paths)} image(s) → {shorten_home(out)}")
            for index, path in enumerate(paths, 1):
                print(f"  {index}. {shorten_home(path)}")
            return 0
        size = parse_size(args.size) if args.size else None
        out = Path(args.output).expanduser() if args.output else default_output(args.kind)
        try:
            capture = _capture(args, out, size)
        except BrowserMissing:
            if not install_browser(assume_yes=args.yes):
                raise ShootError("Playwright's Chromium is not installed; nothing was captured") from None
            capture = _capture(args, out, size)
        print(render_capture(capture, args.kind))
        return _baseline_step(args, capture.path, masks)
    except (ShootError, ValueError, png.PNGError, OSError) as error:
        print(f"shoot: {error}", file=sys.stderr)
        return 1


def run_compare(args, masks: list[Rect]) -> int:
    baseline, actual = Path(args.baseline_image).expanduser(), Path(args.actual).expanduser()
    comparison, diff = compare(png.read(baseline), png.read(actual), threshold=args.threshold, masks=masks)
    if diff is not None and not comparison.passes(args.tolerance):
        out = Path(args.diff).expanduser() if args.diff else actual.with_name(actual.stem + "-diff.png")
        comparison.diff_path = png.write(diff, out)
    status = "matches" if comparison.passes(args.tolerance) else "differs"
    print(render_baseline(BaselineResult(status, comparison), baseline, args.tolerance))
    return 0 if status == "matches" else EXIT_DIFFERS
