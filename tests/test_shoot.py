import json
import os
import shutil
import struct
import subprocess
import zlib

import pytest
from conftest import posix_only

from claude_toolkit import cli, png, shoot
from claude_toolkit.common import EXIT_NEEDS_CONFIRMATION


def solid(width, height, color=(255, 255, 255, 255)) -> png.Image:
    return png.Image.blank(width, height, color)


def paint(image: png.Image, rect: shoot.Rect, color=(255, 0, 0, 255)) -> png.Image:
    copy = png.Image(image.width, image.height, bytearray(image.rgba))
    for y in range(rect.y, rect.y + rect.h):
        for x in range(rect.x, rect.x + rect.w):
            i = (y * copy.width + x) * 4
            copy.rgba[i : i + 4] = bytes(color)
    return copy


def raw_png(width, height, depth, color_type, rows: list[bytes], extra: bytes = b"") -> bytes:
    def chunk(kind, body):
        return struct.pack(">I", len(body)) + kind + body + struct.pack(">I", zlib.crc32(kind + body))

    header = struct.pack(">IIBBBBB", width, height, depth, color_type, 0, 0, 0)
    data = zlib.compress(b"".join(b"\x00" + row for row in rows))
    return png.SIGNATURE + chunk(b"IHDR", header) + extra + chunk(b"IDAT", data) + chunk(b"IEND", b"")


# --- png ------------------------------------------------------------------------


def test_png_round_trip_and_filters(tmp_path):
    image = solid(7, 5, (10, 20, 30, 255))
    image = paint(image, shoot.Rect(2, 1, 3, 2), (200, 100, 50, 128))
    path = png.write(image, tmp_path / "x.png")
    assert png.read(path).rgba == image.rgba


def test_png_reads_low_and_high_bit_depths():
    one_bit = png.decode(raw_png(10, 1, 1, 0, [bytes([0b10100000, 0b01000000])]))
    assert [one_bit.pixel(x, 0)[0] for x in range(10)] == [255, 0, 255, 0, 0, 0, 0, 0, 0, 255]
    palette = struct.pack(">I", 6) + b"PLTE" + b"\xff\x00\x00\x00\x00\xff"
    palette += struct.pack(">I", zlib.crc32(b"PLTE\xff\x00\x00\x00\x00\xff"))
    two_bit = png.decode(raw_png(2, 1, 2, 3, [bytes([0b00010000])], palette))
    assert two_bit.pixel(0, 0) == (255, 0, 0, 255) and two_bit.pixel(1, 0) == (0, 0, 255, 255)
    sixteen = png.decode(raw_png(1, 1, 16, 2, [b"\xff\xff\x80\x00\x00\x00"]))
    assert sixteen.pixel(0, 0) == (255, 128, 0, 255)


def test_png_rejects_what_it_cannot_read():
    with pytest.raises(png.PNGError):
        png.decode(b"GIF89a")
    interlaced = raw_png(1, 1, 8, 2, [b"\x00\x00\x00"]).replace(
        struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 0), struct.pack(">IIBBBBB", 1, 1, 8, 2, 0, 0, 1)
    )
    with pytest.raises(png.PNGError):
        png.decode(interlaced)


# --- comparison -----------------------------------------------------------------


def test_compare_counts_changed_pixels_with_box():
    base = solid(100, 50)
    changed = paint(base, shoot.Rect(10, 20, 5, 4))
    result, diff = shoot.compare(base, changed)
    assert result.differing == 20 and result.box == shoot.Rect(10, 20, 5, 4)
    assert diff is not None and diff.pixel(12, 21)[:3] == (224, 16, 48)
    assert not result.passes(0.1) and result.passes(0.5)


def test_threshold_ignores_small_noise_and_masks_ignore_regions():
    base = solid(40, 40, (100, 100, 100, 255))
    noisy = paint(base, shoot.Rect(0, 0, 40, 40), (104, 97, 100, 255))
    assert shoot.compare(base, noisy, threshold=8)[0].differing == 0
    assert shoot.compare(base, noisy, threshold=2)[0].differing == 1600
    clock = paint(base, shoot.Rect(30, 0, 10, 10))
    masked, diff = shoot.compare(base, clock, masks=[shoot.Rect(30, 0, 10, 10)])
    assert masked.differing == 0 and masked.compared == 1500 and diff is None


def test_size_mismatch_never_passes():
    result, _ = shoot.compare(solid(10, 10), solid(10, 11))
    assert result.size_mismatch and not result.passes(100)


def test_baseline_is_created_then_compared_then_updated(tmp_path):
    shot = png.write(solid(20, 20), tmp_path / "shot.png")
    baseline = tmp_path / "baselines" / "home.png"
    assert shoot.check_baseline(shot, baseline).status == "created"
    assert shoot.check_baseline(shot, baseline).status == "matches"
    png.write(paint(solid(20, 20), shoot.Rect(0, 0, 5, 5)), shot)
    differs = shoot.check_baseline(shot, baseline)
    assert differs.status == "differs" and differs.comparison.diff_path.exists()
    assert shoot.check_baseline(shot, baseline, update=True).status == "updated"
    assert shoot.check_baseline(shot, baseline).status == "matches"


def test_compare_command_exit_codes_and_plain_output(tmp_path, capsys):
    a = png.write(solid(30, 30), tmp_path / "a.png")
    b = png.write(paint(solid(30, 30), shoot.Rect(1, 2, 3, 4)), tmp_path / "b.png")
    assert cli.main(["shoot", "compare", str(a), str(a)]) == 0
    assert cli.main(["shoot", "compare", str(a), str(b)]) == 1
    out = capsys.readouterr().out.splitlines()
    assert out[0].startswith("shoot: matches baseline")
    assert out[1].startswith("shoot: differs from baseline") and "box x=1 y=2 w=3 h=4" in out[1]
    assert "\x1b" not in "".join(out) and (tmp_path / "b-diff.png").exists()
    assert cli.main(["shoot", "compare", str(a), str(b), "--mask", "0,0,10,10"]) == 0


# --- contact sheet ------------------------------------------------------------------


def test_contact_sheet_layout_and_labels(tmp_path):
    paths = [png.write(solid(800, 400, (i * 40, 0, 0, 255)), tmp_path / f"{i}.png") for i in range(5)]
    sheet = shoot.contact_sheet(paths, columns=3, thumb_width=200, gap=8)
    assert (sheet.width, sheet.height) == (3 * 200 + 4 * 8, 2 * 100 + 3 * 8)
    assert sheet.pixel(8 + 2 * 3, 8 + 1 * 3) == (56, 189, 248, 255)  # top stroke of the "1" label
    assert sheet.pixel(8 + 1 * 3, 8 + 1 * 3) == (15, 23, 42, 255)  # label background
    assert shoot.thumbnail(solid(100, 50), 400).width == 100  # never upscaled


# --- parsing --------------------------------------------------------------------------


def test_sizes_masks_and_targets():
    assert shoot.parse_size("1280x720") == (1280, 720)
    for bad in ("1280", "0x10", "axb"):
        with pytest.raises(ValueError):
            shoot.parse_size(bad)
    with pytest.raises(ValueError):
        shoot.Rect.parse("1,2,3")
    assert shoot._web_target("localhost:5173") == "http://localhost:5173"
    assert shoot._web_target("https://example.com") == "https://example.com"
    assert shoot._web_target(__file__).startswith("file://")


# --- web (Playwright mocked) ---------------------------------------------------------------


def fake_web(tmp_path, monkeypatch, *, code=0, result=None):
    calls = []

    def run_web(options):
        calls.append(options)
        if code == 0:
            png.write(solid(options["width"], options["height"]), options["out"])
        payload = json.dumps(result or {"status": 200, "console_errors": [], "page_errors": []})
        return subprocess.CompletedProcess([], code, payload + "\n", "")

    monkeypatch.setattr(shoot, "_run_web", run_web)
    return calls


def test_web_capture_reports_page_problems(tmp_path, monkeypatch, capsys):
    result = {"status": 404, "console_errors": ["boom"], "page_errors": []}
    calls = fake_web(tmp_path, monkeypatch, result=result)
    out = tmp_path / "shot.png"
    code = cli.main(["shoot", "web", "localhost:3000", "-o", str(out), "--size", "320x200", "--mask-selector", "#t"])
    assert code == 0 and out.exists()
    assert calls[0]["url"] == "http://localhost:3000" and calls[0]["mask_selectors"] == ["#t"]
    text = capsys.readouterr().out
    assert "320x200" in text and "note: HTTP 404" in text and "1 console error(s), first: boom" in text


def test_missing_browser_needs_confirmation_without_a_terminal(tmp_path, monkeypatch, capsys):
    fake_web(tmp_path, monkeypatch, code=10)
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)
    assert cli.main(["shoot", "web", "http://x", "-o", str(tmp_path / "s.png")]) == EXIT_NEEDS_CONFIRMATION
    assert "Chromium" in capsys.readouterr().err


def test_web_baseline_differs_exits_1(tmp_path, monkeypatch, capsys):
    fake_web(tmp_path, monkeypatch)
    baseline = png.write(solid(64, 64, (0, 0, 0, 255)), tmp_path / "base.png")
    args = ["shoot", "web", "http://x", "-o", str(tmp_path / "s.png"), "--size", "64x64", "--baseline", str(baseline)]
    assert cli.main(args) == 1
    assert "differs from baseline" in capsys.readouterr().out


# --- godot (fake binary) ---------------------------------------------------------------------

FAKE_GODOT = """#!/bin/sh
if [ "$1" = --version ]; then echo 4.3.stable.official; exit 0; fi
project=""; movie=""
while [ $# -gt 0 ]; do
  case "$1" in
    --path) shift; project=$1 ;;
    --write-movie) shift; movie=$1 ;;
  esac
  shift
done
base=${movie%.png}
last="$project/big.png"
[ -f "$project/override.cfg" ] && last="$project/small.png"
cp "$last" "${base}00000001.png"
cp "$project/big.png" "${base}00000000.png"
echo "SCRIPT ERROR: Invalid call" >&2
"""


@posix_only
def test_godot_uses_override_for_size_and_keeps_the_last_frame(tmp_path, monkeypatch):
    project = tmp_path / "game"
    project.mkdir()
    (project / "project.godot").write_text("config_version=5\n")
    png.write(solid(64, 36), project / "small.png")
    png.write(solid(128, 72), project / "big.png")
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "godot").write_text(FAKE_GODOT)
    (bin_dir / "godot").chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ['PATH']}")
    monkeypatch.setenv("DISPLAY", ":0")
    real_which = shutil.which
    monkeypatch.setattr(shoot.shutil, "which", lambda name: None if name == "Xvfb" else real_which(name))

    capture = shoot.capture_godot(project, tmp_path / "a.png", scene=None, size=(64, 36), frames=5)
    assert (capture.width, capture.height) == (64, 36)
    assert not (project / "override.cfg").exists()
    assert capture.notes and "SCRIPT ERROR" in capture.notes[0]
    capture = shoot.capture_godot(project, tmp_path / "b.png", scene="res://x.tscn", size=None, frames=5)
    assert (capture.width, capture.height) == (128, 72)


def test_godot_refuses_to_touch_an_existing_override(tmp_path):
    (tmp_path / "project.godot").write_text("")
    (tmp_path / "override.cfg").write_text("[display]\n")
    with pytest.raises(shoot.ShootError, match=r"override\.cfg"), shoot._viewport_override(tmp_path, (10, 10)):
        pass
    assert (tmp_path / "override.cfg").read_text() == "[display]\n"


# --- desktop (real Xvfb when available) ---------------------------------------------------------


@pytest.mark.skipif(
    not shutil.which("Xvfb") or not (shutil.which("import") or shutil.which("magick") or shutil.which("ffmpeg")),
    reason="needs Xvfb and ImageMagick or ffmpeg",
)
def test_desktop_capture_on_a_private_display(tmp_path):
    capture = shoot.capture_desktop(["sleep", "5"], tmp_path / "d.png", size=(320, 240), delay=0.5)
    image = png.read(capture.path)
    assert (image.width, image.height) == (320, 240)


def test_desktop_without_xvfb_explains_what_is_missing(tmp_path, monkeypatch, capsys):
    real_which = shutil.which
    monkeypatch.setattr(shoot.shutil, "which", lambda name: None if name == "Xvfb" else real_which(name))
    assert cli.main(["shoot", "desktop", "-o", str(tmp_path / "d.png"), "--", "sleep", "1"]) == 1
    expected = "needs an X server" if os.name == "nt" else "Xvfb is not installed"
    assert expected in capsys.readouterr().err
