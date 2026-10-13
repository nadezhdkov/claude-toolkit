# `ctk audiocheck`

Checks audio files for the problems a person would otherwise only hear:
clipping, wrong loudness, silence at the edges, DC offset and clicks at loop
points. It also writes waveform and spectrogram images that an agent can read.

```bash
ctk audiocheck assets/sfx                      # every audio file below a directory
ctk audiocheck music/theme.ogg --loop          # also check the loop point
ctk audiocheck voice/*.wav --target -16        # require -16 LUFS ± 1
ctk audiocheck boss.ogg --images               # waveform + spectrogram PNGs
ctk audiocheck assets --json                   # machine-readable report
```

Formats: anything ffmpeg decodes (`.wav`, `.ogg`, `.mp3`, `.flac`, `.opus`,
`.m4a`, `.aiff`…). Directories are searched recursively, skipping `.git`,
`node_modules`, `.venv` and Godot's `.godot`/`.import`.

## Checks

| Check | Measured with | Level |
|---|---|---|
| Integrated loudness, loudness range, true peak | EBU R128 (`ebur128` filter) | error outside `--target` ± `--lufs-tolerance` (only when `--target` is given) |
| True peak | R128 true peak | warn above `--max-true-peak` (default -1 dBTP) |
| Clipping | runs of 3+ samples stuck at a channel's peak value (16-bit PCM) | error; catches clipped audio that was attenuated later, ignores channels below half scale |
| Silent file | `silencedetect` below `--silence-db` (default -60 dBFS) | error |
| Leading / trailing silence | `silencedetect` | warn above `--max-lead` (0.1 s) / `--max-trail` (1 s) |
| Inner gaps | `silencedetect` | info for gaps of `--max-gap` (2 s) or more |
| DC offset | `astats` | warn above 0.01 |
| Loop seam (`--loop`) | jump from the last sample to the first vs the 95th-percentile step around it; RMS of the first and last 50 ms | error for a click (jump above 4× the typical step and above 0.05 of full scale); warn for a level jump above 6 dB or silence at the loop point |
| Unreadable file | ffprobe/ffmpeg | error |

## Output

```
audiocheck: sfx/clipped.wav · 1.00s · 48 kHz · mono · pcm_s16le
  loudness -4.1 LUFS · LRA 0.0 LU · true peak -5.9 dBTP
  error: clipping: 20,160 samples in 440 flat run(s), first at 0.00s
audiocheck: music/theme.ogg · 92.40s · 44.1 kHz · stereo · vorbis
  loudness -15.8 LUFS · LRA 4.2 LU · true peak -1.3 dBTP · seam jump 0.004
summary: 2 file(s) · 1 with errors · 0 with warnings only
```

`--images [DIR]` writes `<name>-wave.png` (one lane per channel) and
`<name>-spectrum.png` (log-frequency spectrogram with a dBFS legend) to `DIR`,
or to `~/.cache/claude-toolkit/audiocheck/`.

## Exit codes

`0` when no file has errors (with `--strict`, no warnings either); `1`
otherwise, or when ffmpeg is missing or no audio file was found.

## Requirements

`ffmpeg` and `ffprobe` (`ctk doctor --toolkit` shows the install command).

## Done criteria (tested in `tests/test_audiocheck.py`)

- Clean, clipped (including clipped then attenuated), padded, silent and broken
  files are classified correctly; loudness agrees with R128.
- A loop with whole cycles passes; one cut mid-cycle is reported as a click.
- `--images` writes both PNGs per file; plain output has no colour codes.
- A missing ffmpeg is explained instead of crashing.
