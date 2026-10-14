"""``ctk audiocheck``: catch broken audio before a person has to listen to it.

Per file: integrated loudness, loudness range and true peak (EBU R128 through
ffmpeg's ``ebur128``), DC offset, clipping (flat tops at the peak value),
leading/trailing silence and long gaps, and, with ``--loop``, clicks and level
jumps at the loop point. ``--images`` writes waveform and spectrogram PNGs an
agent can read.

ffmpeg does the decoding and the R128 measurement; clipping and loop seams are
computed from 16-bit PCM with byte-level searches, so long files stay fast.
"""

from __future__ import annotations

import array
import itertools
import json
import math
import os
import re
import shutil
import struct
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .style import Spinner, Style, shorten_home

AUDIO_SUFFIXES = {".wav", ".ogg", ".oga", ".mp3", ".flac", ".opus", ".m4a", ".aac", ".aif", ".aiff", ".wma", ".webm"}
SKIP_DIRS = {".git", "node_modules", ".venv", ".godot", ".import", "__pycache__"}
FULL_SCALE = 32768.0
SEAM_WINDOW = 0.05  # seconds compared on each side of the loop point
TIMEOUT = 300


class AudioError(Exception):
    """The file could not be analysed."""


@dataclass
class Finding:
    level: str  # error, warn, info
    message: str


@dataclass
class Report:
    path: str
    duration: float = 0.0
    sample_rate: int = 0
    channels: int = 0
    codec: str = ""
    integrated_lufs: float | None = None
    loudness_range: float | None = None
    true_peak_db: float | None = None
    sample_peak_db: float | None = None
    dc_offset: float | None = None
    clipped_samples: int = 0
    clip_runs: int = 0
    first_clip: float | None = None
    leading_silence: float = 0.0
    trailing_silence: float = 0.0
    gaps: list[tuple[float, float]] = field(default_factory=list)
    seam_jump: float | None = None
    seam_typical: float | None = None
    seam_level_db: float | None = None
    images: list[str] = field(default_factory=list)
    findings: list[Finding] = field(default_factory=list)

    @property
    def errors(self) -> int:
        return sum(1 for f in self.findings if f.level == "error")

    @property
    def warnings(self) -> int:
        return sum(1 for f in self.findings if f.level == "warn")


@dataclass
class Limits:
    target_lufs: float | None = None
    lufs_tolerance: float = 1.0
    max_true_peak: float = -1.0
    max_lead: float = 0.1
    max_trail: float = 1.0
    max_gap: float = 2.0
    silence_db: float = -60.0
    loop: bool = False


# --- Running ffmpeg ------------------------------------------------------------------


def _ffmpeg(*args: str) -> subprocess.CompletedProcess:
    try:
        return subprocess.run(
            ["ffmpeg", "-hide_banner", "-nostdin", *args], capture_output=True, timeout=TIMEOUT, check=False
        )
    except FileNotFoundError as missing:
        raise AudioError("ffmpeg is not installed (see `ctk doctor --toolkit`)") from missing
    except subprocess.TimeoutExpired as slow:
        raise AudioError(f"ffmpeg took longer than {TIMEOUT}s") from slow


def probe(path: Path) -> tuple[float, int, int, str]:
    """(duration, sample rate, channels, codec) of the first audio stream."""
    try:
        done = subprocess.run(
            ["ffprobe", "-v", "error", "-select_streams", "a:0", "-show_entries",
             "stream=codec_name,sample_rate,channels:format=duration", "-of", "json", str(path)],
            capture_output=True, text=True, timeout=60, check=False, encoding="utf-8", errors="replace",
        )  # fmt: skip
    except FileNotFoundError as missing:
        raise AudioError("ffprobe is not installed (it ships with ffmpeg)") from missing
    try:
        data = json.loads(done.stdout or "{}")
    except json.JSONDecodeError:
        data = {}
    streams = data.get("streams") or []
    if done.returncode != 0 or not streams:
        detail = (done.stderr or "").strip().splitlines()
        raise AudioError(f"no audio stream ({detail[-1] if detail else 'unreadable file'})")
    stream = streams[0]
    duration = float(data.get("format", {}).get("duration") or 0)
    return duration, int(stream.get("sample_rate") or 0), int(stream.get("channels") or 0), stream.get("codec_name", "")


NUMBER = r"(-?(?:\d+(?:\.\d+)?|inf))"


def _number(pattern: str, text: str) -> float | None:
    matches = re.findall(pattern, text)
    if not matches:
        return None
    value = float(matches[-1])
    return value if math.isfinite(value) else None


def measure(path: Path, report: Report, limits: Limits) -> None:
    """Loudness, true peak, DC offset and silences from one ffmpeg pass."""
    filters = (
        "astats=measure_overall=DC_offset+Peak_level:measure_perchannel=none,"
        f"silencedetect=n={limits.silence_db}dB:d=0.05,"
        "ebur128=peak=true:framelog=quiet"
    )
    done = _ffmpeg("-nostats", "-i", str(path), "-af", filters, "-f", "null", "-")
    text = done.stderr.decode("utf-8", "replace")
    if done.returncode != 0:
        raise AudioError(f"ffmpeg could not decode the file: {text.strip().splitlines()[-1] if text.strip() else ''}")
    summary = text[text.rfind("Summary:") :] if "Summary:" in text else ""
    report.integrated_lufs = _number(rf"I:\s+{NUMBER} LUFS", summary)
    report.loudness_range = _number(rf"LRA:\s+{NUMBER} LU\b", summary)
    report.true_peak_db = _number(rf"Peak:\s+{NUMBER} dBFS", summary)
    report.dc_offset = _number(rf"DC offset: {NUMBER}", text)
    report.sample_peak_db = _number(rf"Peak level dB: {NUMBER}", text)
    _silences(text, report, limits)


def _silences(text: str, report: Report, limits: Limits) -> None:
    starts = [float(v) for v in re.findall(r"silence_start: (-?[\d.]+)", text)]
    ends = [float(v) for v in re.findall(r"silence_end: (-?[\d.]+)", text)]
    duration = report.duration
    spans = [(max(0.0, start), ends[i] if i < len(ends) else duration) for i, start in enumerate(starts)]
    for start, end in spans:
        if start <= 0.001:
            report.leading_silence = end
        elif end >= duration - 0.01:
            report.trailing_silence = end - start
        elif end - start >= limits.max_gap:
            report.gaps.append((round(start, 3), round(end - start, 3)))


def decode_pcm(path: Path, channels: int, rate: int) -> array.array:
    done = _ffmpeg("-v", "error", "-i", str(path), "-f", "s16le", "-acodec", "pcm_s16le",
                   "-ac", str(channels), "-ar", str(rate), "-")  # fmt: skip
    if done.returncode != 0:
        raise AudioError("ffmpeg could not decode the file to PCM")
    samples = array.array("h")
    samples.frombytes(done.stdout[: len(done.stdout) // 2 * 2])
    if sys.byteorder == "big":
        samples.byteswap()
    return samples


def find_clipping(samples: array.array, channels: int, rate: int, min_run: int = 3) -> tuple[int, int, float | None]:
    """(clipped samples, runs, first time) where a channel stays at its peak for ``min_run`` samples or more.

    Flat tops at the channel's extreme value are what clipping leaves behind,
    whatever the final level (a clipped signal that was then attenuated too).
    Quiet channels (peak below half scale) are skipped.
    """
    clipped = runs = 0
    first: float | None = None
    for channel in range(channels):
        data = samples[channel::channels]
        if not data:
            continue
        raw = data.tobytes() if sys.byteorder == "little" else _swapped(data)
        for value in {max(data), min(data)}:
            if abs(value) < FULL_SCALE / 2:
                continue
            pattern = re.compile(b"(?:" + re.escape(struct.pack("<h", value)) + b"){%d,}" % min_run)
            for match in pattern.finditer(raw):
                if match.start() % 2:
                    continue
                length = (match.end() - match.start()) // 2
                clipped += length
                runs += 1
                when = match.start() // 2 / rate
                first = when if first is None else min(first, when)
    return clipped, runs, first


def _swapped(data: array.array) -> bytes:
    copy = array.array("h", data)
    copy.byteswap()
    return copy.tobytes()


def _rms_db(values: list[int]) -> float:
    if not values:
        return -120.0
    rms = math.sqrt(sum(v * v for v in values) / len(values)) / FULL_SCALE
    return 20 * math.log10(rms) if rms > 0 else -120.0


def loop_seam(samples: array.array, channels: int, rate: int) -> tuple[float, float, float]:
    """(jump at the seam, typical step near it, level change in dB), as fractions of full scale."""
    window = max(2, int(rate * SEAM_WINDOW))
    jumps, typical, levels = [], [], []
    for channel in range(channels):
        data = samples[channel::channels]
        if len(data) < 4:
            continue
        head, tail = list(data[:window]), list(data[-window:])
        jumps.append(abs(head[0] - tail[-1]) / FULL_SCALE)
        steps = sorted(abs(b - a) for seq in (head, tail) for a, b in itertools.pairwise(seq))
        typical.append(steps[int(len(steps) * 0.95)] / FULL_SCALE if steps else 0.0)
        levels.append(abs(_rms_db(head) - _rms_db(tail)))
    if not jumps:
        return 0.0, 0.0, 0.0
    return max(jumps), max(typical), max(levels)


def render_images(path: Path, directory: Path) -> list[Path]:
    directory.mkdir(parents=True, exist_ok=True)
    stem = re.sub(r"[^A-Za-z0-9._-]+", "-", path.stem)
    wave, spectrum = directory / f"{stem}-wave.png", directory / f"{stem}-spectrum.png"
    waveform = (
        "color=c=0x0f172a:s=1200x240[bg];"
        "[0:a]showwavespic=s=1200x240:split_channels=1:draw=full:colors=0x38bdf8|0x22d3ee[w];"
        "[bg][w]overlay=format=auto"
    )
    _ffmpeg("-v", "error", "-y", "-i", str(path), "-filter_complex", waveform, "-frames:v", "1", str(wave))
    spectrogram = "showspectrumpic=s=1200x400:legend=1:color=intensity:scale=log"
    _ffmpeg("-v", "error", "-y", "-i", str(path), "-lavfi", spectrogram, str(spectrum))
    return [image for image in (wave, spectrum) if image.exists()]


# --- Judging -----------------------------------------------------------------------------


def judge(report: Report, limits: Limits) -> None:
    add = report.findings.append
    if report.leading_silence >= report.duration - 0.01 and report.duration > 0:
        add(Finding("error", f"silent: nothing above {limits.silence_db:g} dBFS"))
        return
    if report.clipped_samples:
        add(Finding("error", f"clipping: {report.clipped_samples:,} samples in {report.clip_runs:,} flat run(s), "
                             f"first at {report.first_clip:.2f}s"))  # fmt: skip
    if limits.target_lufs is not None:
        if report.integrated_lufs is None:
            add(Finding("warn", "loudness not measurable (file shorter than 0.4s or too quiet)"))
        elif abs(report.integrated_lufs - limits.target_lufs) > limits.lufs_tolerance:
            add(Finding("error", f"loudness {report.integrated_lufs:.1f} LUFS, target {limits.target_lufs:g} "
                                 f"± {limits.lufs_tolerance:g}"))  # fmt: skip
    if report.true_peak_db is not None and report.true_peak_db > limits.max_true_peak:
        add(Finding("warn", f"true peak {report.true_peak_db:.1f} dBTP above {limits.max_true_peak:g}"))
    if report.dc_offset is not None and abs(report.dc_offset) > 0.01:
        add(Finding("warn", f"DC offset {report.dc_offset:+.3f}"))
    if report.leading_silence > limits.max_lead:
        add(Finding("warn", f"leading silence {report.leading_silence:.2f}s"))
    if report.trailing_silence > limits.max_trail:
        add(Finding("warn", f"trailing silence {report.trailing_silence:.2f}s"))
    for start, length in report.gaps:
        add(Finding("info", f"silent gap of {length:.2f}s at {start:.2f}s"))
    if limits.loop and report.seam_jump is not None:
        typical = report.seam_typical or 0.0
        if report.seam_jump > max(0.05, 4 * typical):
            add(Finding("error", f"loop seam click: jump {report.seam_jump:.3f} of full scale "
                                 f"(typical step {typical:.3f})"))  # fmt: skip
        if (report.seam_level_db or 0) > 6:
            add(Finding("warn", f"loop seam level jump {report.seam_level_db:.1f} dB"))
        if report.leading_silence > 0.01 or report.trailing_silence > 0.01:
            add(Finding("warn", "silence at the loop point creates an audible gap"))


def analyse(path: Path, limits: Limits, images_dir: Path | None = None) -> Report:
    report = Report(str(path))
    try:
        report.duration, report.sample_rate, report.channels, report.codec = probe(path)
        measure(path, report, limits)
        samples = decode_pcm(path, report.channels, report.sample_rate)
        report.clipped_samples, report.clip_runs, report.first_clip = find_clipping(
            samples, report.channels, report.sample_rate
        )
        if limits.loop:
            report.seam_jump, report.seam_typical, report.seam_level_db = loop_seam(
                samples, report.channels, report.sample_rate
            )
        if images_dir is not None:
            report.images = [str(image) for image in render_images(path, images_dir)]
    except AudioError as error:
        report.findings.append(Finding("error", str(error)))
        return report
    judge(report, limits)
    return report


def collect(paths: list[Path]) -> list[Path]:
    found: list[Path] = []
    for path in paths:
        if path.is_dir():
            for directory, dirs, files in os.walk(path):
                dirs[:] = sorted(d for d in dirs if d not in SKIP_DIRS)
                found += [
                    Path(directory) / name for name in sorted(files) if Path(name).suffix.lower() in AUDIO_SUFFIXES
                ]
        else:
            found.append(path)
    return found


# --- Output ---------------------------------------------------------------------------------


def _channels(count: int) -> str:
    return {1: "mono", 2: "stereo"}.get(count, f"{count} ch")


def _fmt(value: float | None, unit: str, digits: int = 1) -> str:
    return f"{value:.{digits}f} {unit}" if value is not None else f"n/a {unit}"


def describe(report: Report) -> tuple[str, str]:
    if not report.sample_rate:
        return shorten_home(report.path), ""
    head = (
        f"{shorten_home(report.path)} · {report.duration:.2f}s · {report.sample_rate / 1000:g} kHz · "
        f"{_channels(report.channels)} · {report.codec}"
    )
    facts = [
        f"loudness {_fmt(report.integrated_lufs, 'LUFS')}",
        f"LRA {_fmt(report.loudness_range, 'LU')}",
        f"true peak {_fmt(report.true_peak_db, 'dBTP')}",
    ]
    if report.seam_jump is not None:
        facts.append(f"seam jump {report.seam_jump:.3f}")
    return head, " · ".join(facts)


def render(reports: list[Report], st: Style | None = None) -> str:
    st = st or Style.detect()
    lines: list[str] = []
    for report in reports:
        head, facts = describe(report)
        if not st.enabled:
            lines.append(f"audiocheck: {head}")
            if report.sample_rate:
                lines.append(f"  {facts}")
            lines += [f"  {finding.level}: {finding.message}" for finding in report.findings]
            lines += [f"  image: {shorten_home(image)}" for image in report.images]
            continue
        symbol = st.err("✗", bold=True) if report.errors else st.warn("!", bold=True) if report.warnings else st.ok("✓")
        lines.append(f"  {symbol} {st.bold(head)}")
        if report.sample_rate:
            lines.append(f"      {st.muted(facts)}")
        for finding in report.findings:
            mark = {"error": st.err("✗"), "warn": st.warn("!"), "info": st.muted("·")}[finding.level]
            lines.append(f"      {mark} {finding.message}")
        lines += [f"      {st.muted('image')} {st.accent2(shorten_home(image))}" for image in report.images]
    failed = sum(1 for r in reports if r.errors)
    warned = sum(1 for r in reports if r.warnings and not r.errors)
    summary = f"{len(reports)} file(s) · {failed} with errors · {warned} with warnings only"
    if st.enabled:
        status = st.err("✗", bold=True) if failed else st.warn("!", bold=True) if warned else st.ok("✓", bold=True)
        return "\n".join([st.header("ctk audiocheck"), "", *lines, "", f"  {status} {st.muted(summary)}"])
    return "\n".join([*lines, f"summary: {summary}"])


def to_json(reports: list[Report]) -> str:
    return json.dumps([asdict(report) for report in reports], indent=2)


def default_images_dir() -> Path:
    base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "claude-toolkit" / "audiocheck"


def run(args) -> int:
    if not shutil.which("ffmpeg"):
        print("audiocheck: ffmpeg is not installed (see `ctk doctor --toolkit`)", file=sys.stderr)
        return 1
    files = collect([Path(p).expanduser() for p in args.paths])
    if not files:
        print("audiocheck: no audio files found", file=sys.stderr)
        return 1
    limits = Limits(
        target_lufs=args.target,
        lufs_tolerance=args.lufs_tolerance,
        max_true_peak=args.max_true_peak,
        max_lead=args.max_lead,
        max_trail=args.max_trail,
        max_gap=args.max_gap,
        silence_db=args.silence_db,
        loop=args.loop,
    )
    images = None
    if args.images is not None:
        images = Path(args.images).expanduser() if args.images else default_images_dir()
    with Spinner(f"analysing {len(files)} file(s)"):
        reports = [analyse(path, limits, images) for path in files]
    print(to_json(reports) if args.json else render(reports))
    failing = any(r.errors or (args.strict and r.warnings) for r in reports)
    return 1 if failing else 0
