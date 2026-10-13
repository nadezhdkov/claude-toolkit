import array
import json
import math
import shutil
import wave

import pytest

from claude_toolkit import audiocheck, cli

RATE = 48000
needs_ffmpeg = pytest.mark.skipif(not shutil.which("ffmpeg") or not shutil.which("ffprobe"), reason="needs ffmpeg")


def tone(seconds, freq=440.0, amp=0.5, rate=RATE, phase=0.0) -> list[float]:
    return [amp * math.sin(phase + 2 * math.pi * freq * i / rate) for i in range(int(seconds * rate))]


def pcm(values, channels=1) -> array.array:
    data = array.array("h")
    for value in values:
        sample = max(-32768, min(32767, round(value * 32767)))
        data.extend([sample] * channels)
    return data


def write_wav(path, values, channels=1, rate=RATE):
    with wave.open(str(path), "wb") as out:
        out.setnchannels(channels)
        out.setsampwidth(2)
        out.setframerate(rate)
        out.writeframes(pcm(values, channels).tobytes())
    return path


# --- analysis without ffmpeg --------------------------------------------------------


def test_clipping_is_found_as_flat_tops_even_after_attenuation():
    clean = pcm(tone(0.5, amp=0.9))
    assert audiocheck.find_clipping(clean, 1, RATE)[0] == 0
    clipped = pcm([max(-0.6, min(0.6, v)) for v in tone(0.5, amp=0.9)], channels=2)
    samples, runs, first = audiocheck.find_clipping(clipped, 2, RATE)
    assert runs == 2 * 2 * 220 and samples > 0 and first is not None and first < 0.01


def test_quiet_channels_are_not_reported_as_clipped():
    quiet = pcm([max(-0.1, min(0.1, v)) for v in tone(0.2, amp=0.3)])
    assert audiocheck.find_clipping(quiet, 1, RATE)[0] == 0


def test_loop_seam_tells_a_clean_loop_from_a_click():
    clean = pcm(tone(1.0, freq=480))  # whole cycles: the end flows into the start
    clicky = pcm(tone(1.0, freq=480, phase=math.pi / 2))[: RATE - 25]
    jump, typical, _ = audiocheck.loop_seam(clean, 1, RATE)
    assert jump <= typical * 1.5
    jump, typical, _ = audiocheck.loop_seam(clicky, 1, RATE)
    assert jump > 4 * typical and jump > 0.05


def test_silences_from_silencedetect_output():
    report = audiocheck.Report("x", duration=10.0)
    text = "\n".join(
        [
            "silence_start: 0",
            "silence_end: 0.25 | silence_duration: 0.25",
            "silence_start: 4.0",
            "silence_end: 7.0 | silence_duration: 3.0",
            "silence_start: 9.0",
            "silence_end: 10.0 | silence_duration: 1.0",
        ]
    )
    audiocheck._silences(text, report, audiocheck.Limits())
    assert (report.leading_silence, report.trailing_silence, report.gaps) == (0.25, 1.0, [(4.0, 3.0)])


def test_judge_levels():
    report = audiocheck.Report(
        "x", duration=3, integrated_lufs=-20.0, true_peak_db=-0.2, dc_offset=0.02, leading_silence=0.3
    )
    audiocheck.judge(report, audiocheck.Limits(target_lufs=-16))
    levels = {finding.message.split()[0]: finding.level for finding in report.findings}
    assert levels == {"loudness": "error", "true": "warn", "DC": "warn", "leading": "warn"}
    silent = audiocheck.Report("y", duration=1, leading_silence=1.0)
    audiocheck.judge(silent, audiocheck.Limits())
    assert [f.level for f in silent.findings] == ["error"]


def test_collect_walks_directories_and_skips_vendored(tmp_path):
    for name in ("a.wav", "b.OGG", "notes.txt", "node_modules/x.wav", "sfx/c.flac"):
        (tmp_path / name).parent.mkdir(parents=True, exist_ok=True)
        (tmp_path / name).write_bytes(b"")
    found = [path.relative_to(tmp_path).as_posix() for path in audiocheck.collect([tmp_path])]
    assert found == ["a.wav", "b.OGG", "sfx/c.flac"]


def test_missing_ffmpeg_is_explained(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(audiocheck.shutil, "which", lambda name: None)
    assert cli.main(["audiocheck", str(tmp_path)]) == 1
    assert "ffmpeg is not installed" in capsys.readouterr().err


# --- end to end with ffmpeg ---------------------------------------------------------------


@needs_ffmpeg
def test_problem_files_are_classified(tmp_path, capsys):
    write_wav(tmp_path / "good.wav", tone(1.0, amp=0.3))
    write_wav(tmp_path / "clipped.wav", [max(-0.5, min(0.5, v)) for v in tone(1.0, amp=0.95)])
    write_wav(tmp_path / "padded.wav", [0.0] * (RATE // 2) + tone(1.0, amp=0.3) + [0.0] * (RATE * 2), channels=2)
    write_wav(tmp_path / "silent.wav", [0.0] * RATE)
    (tmp_path / "broken.wav").write_bytes(b"not audio")
    assert cli.main(["audiocheck", str(tmp_path), "--json"]) == 1
    reports = {r["path"].rsplit("/", 1)[1]: r for r in json.loads(capsys.readouterr().out)}

    def levels(name):
        return [(f["level"], f["message"].split(":")[0].split(" ")[0]) for f in reports[name]["findings"]]

    assert levels("good.wav") == []
    assert reports["good.wav"]["integrated_lufs"] == pytest.approx(-13.5, abs=1.5)
    assert ("error", "clipping") in levels("clipped.wav")
    assert levels("padded.wav") == [("warn", "leading"), ("warn", "trailing")]
    assert reports["padded.wav"]["leading_silence"] == pytest.approx(0.5, abs=0.02)
    assert levels("silent.wav") == [("error", "silent")]
    assert levels("broken.wav")[0][0] == "error"


@needs_ffmpeg
def test_loop_target_images_and_plain_output(tmp_path, capsys):
    write_wav(tmp_path / "loop.wav", tone(1.0, freq=480, amp=0.4))
    write_wav(tmp_path / "click.wav", tone(1.0, freq=480, amp=0.4, phase=math.pi / 2)[: RATE - 25])
    images = tmp_path / "img"
    code = cli.main(["audiocheck", str(tmp_path / "loop.wav"), str(tmp_path / "click.wav"), "--loop",
                     "--target", "-30", "--images", str(images)])  # fmt: skip
    out = capsys.readouterr().out
    assert code == 1 and "\x1b" not in out
    lines = out.splitlines()
    assert lines[0].startswith("audiocheck: ") and lines[0].endswith("loop.wav · 1.00s · 48 kHz · mono · pcm_s16le")
    assert "error: loop seam click" in out and out.count("loop seam click") == 1
    assert out.count("error: loudness") == 2  # both are far louder than -30 LUFS
    assert sorted(p.name for p in images.iterdir()) == [
        "click-spectrum.png", "click-wave.png", "loop-spectrum.png", "loop-wave.png",
    ]  # fmt: skip
    assert lines[-1].startswith("summary: 2 file(s)")
