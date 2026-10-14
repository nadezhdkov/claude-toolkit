#!/usr/bin/env python3
"""Run the ctk benchmark: each case with and without the plugin, each run in a clean container.

    benchmark/run.py                       # every case, 3 runs per arm
    benchmark/run.py --case long-test-output --runs 1
    benchmark/run.py --arms with           # only the plugin arm

Cases live in benchmark/cases/<name>/ in the `claude plugin eval` layout
(prompt.md + graders/*.md, case.yaml for the scaffold) plus checks/*.sh,
scripts that run inside the container after Claude finishes and pass with
exit 0. Credentials come from benchmark/.env (see .env.example) and are
passed to Docker by name only, never on a command line or into a file.

Standard library only, like ctk.
"""

from __future__ import annotations

import argparse
import fnmatch
import hashlib
import json
import os
import re
import shlex
import shutil
import statistics
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass, field
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parent
CASES = HERE / "cases"
RESULTS = HERE / "results"
CREDENTIALS = ("CLAUDE_CODE_OAUTH_TOKEN", "ANTHROPIC_API_KEY")
PLUGIN_IN_IMAGE = "/opt/ctk/plugin"
USER_CLAUDE_MD = """# Personal preferences

- Explain what you changed in a short summary at the end.
- Prefer small, focused changes and keep the existing code style."""

# A run that hits these never did the task: stop the suite instead of scoring it.
LIMIT_ERRORS = re.compile(r"session limit|usage limit|rate limit|credit balance|overloaded", re.IGNORECASE)
USAGE_KEYS = ("input_tokens", "cache_creation_input_tokens", "cache_read_input_tokens", "output_tokens")


# --- Case files ---------------------------------------------------------------


def _scalar(text: str):
    text = text.strip()
    if not text:
        return ""
    if text[0] in "\"'" and text[-1] == text[0]:
        return text[1:-1]
    if text.startswith("[") and text.endswith("]"):
        return [_scalar(part) for part in _split(text[1:-1]) if part.strip()]
    if text.startswith("{") and text.endswith("}"):
        pairs = (part.split(":", 1) for part in _split(text[1:-1]) if ":" in part)
        return {key.strip(): _scalar(value) for key, value in pairs}
    if re.fullmatch(r"-?\d+", text):
        return int(text)
    if re.fullmatch(r"-?\d+\.\d+", text):
        return float(text)
    return {"true": True, "false": False}.get(text, text)


def _split(text: str) -> list[str]:
    """Split on commas outside quotes and brackets."""
    parts, depth, quote, current = [], 0, "", ""
    for char in text:
        if quote:
            quote = "" if char == quote else quote
        elif char in "\"'":
            quote = char
        elif char in "[{":
            depth += 1
        elif char in "]}":
            depth -= 1
        elif char == "," and depth == 0:
            parts.append(current)
            current = ""
            continue
        current += char
    parts.append(current)
    return parts


def parse_frontmatter(text: str) -> tuple[dict, str]:
    """The small YAML subset the cases use: `key: scalar | [list] | {map}` and block lists."""
    if not text.startswith("---\n"):
        return {}, text
    _, block, body = text.split("---\n", 2)
    data: dict = {}
    key = None
    for line in block.splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if line.startswith((" ", "\t")) and line.strip().startswith("- ") and key:
            data.setdefault(key, [])
            if isinstance(data[key], list):
                data[key].append(_scalar(line.strip()[2:]))
            continue
        name, _, value = line.partition(":")
        key = name.strip()
        data[key] = _scalar(value) if value.strip() else []
    return data, body.strip()


@dataclass
class Grader:
    name: str
    type: str
    options: dict
    body: str = ""
    weight: float = 1.0
    arm: str = ""  # "with-only" | "both" | ""


@dataclass
class Case:
    name: str
    path: Path
    prompt: str
    runs: int = 3
    max_turns: int = 20
    timeout: int = 600
    graders: list[Grader] = field(default_factory=list)
    setup: Path | None = None


def load_case(path: Path) -> Case:
    meta, prompt = parse_frontmatter((path / "prompt.md").read_text(encoding="utf-8"))
    case = Case(
        name=str(meta.get("name") or path.name),
        path=path,
        prompt=prompt,
        runs=int(meta.get("runs", 3)),
        max_turns=int(meta.get("max_turns", 20)),
        timeout=int(meta.get("timeout_seconds", 600)),
    )
    setup = path / "setup.sh"
    case.setup = setup if setup.exists() else None
    for file in sorted((path / "graders").glob("*.md")):
        options, body = parse_frontmatter(file.read_text(encoding="utf-8"))
        kind = str(options.pop("type", ""))
        weight = float(options.pop("weight", 1))
        arm = str(options.pop("arm", ""))
        case.graders.append(Grader(file.stem, kind, options, body, weight, arm))
    for file in sorted((path / "checks").glob("*.sh")):
        case.graders.append(Grader(file.stem, "check", {"script": file.name}))
    if not case.graders:
        raise ValueError(f"{path}: a case needs at least one grader")
    return case


def find_cases(pattern: str | None) -> list[Case]:
    dirs = sorted(p for p in CASES.iterdir() if (p / "prompt.md").exists()) if CASES.is_dir() else []
    return [load_case(d) for d in dirs if not pattern or fnmatch.fnmatch(d.name, pattern)]


# --- Transcript ------------------------------------------------------------------


@dataclass
class Transcript:
    lines: list[dict]
    final: str = ""
    tool_calls: list[tuple[str, dict]] = field(default_factory=list)
    usage: dict = field(default_factory=lambda: dict.fromkeys(USAGE_KEYS, 0))
    cost: float = 0.0
    turns: int = 0
    error: str | None = None

    @classmethod
    def parse(cls, text: str) -> Transcript:
        lines = []
        for raw in text.splitlines():
            try:
                lines.append(json.loads(raw))
            except json.JSONDecodeError:
                continue
        transcript = cls(lines)
        seen: set[str] = set()
        summed = dict.fromkeys(USAGE_KEYS, 0)
        for line in lines:
            message = line.get("message") if isinstance(line.get("message"), dict) else {}
            if line.get("type") == "assistant":
                for block in message.get("content") or []:
                    if isinstance(block, dict) and block.get("type") == "tool_use":
                        transcript.tool_calls.append((str(block.get("name")), block.get("input") or {}))
                usage, key = message.get("usage"), message.get("id")
                if isinstance(usage, dict) and key not in seen:  # one message can span several lines
                    seen.add(key)
                    for name in summed:
                        summed[name] += int(usage.get(name) or 0)
            elif line.get("type") == "result":
                transcript.final = str(line.get("result") or "")
                transcript.cost = float(line.get("total_cost_usd") or 0)
                transcript.turns = int(line.get("num_turns") or 0)
                if line.get("is_error"):
                    transcript.error = transcript.final[:200] or str(line.get("subtype") or "error")
        transcript.usage = summed
        return transcript

    @property
    def context_tokens(self) -> int:
        """Everything the model read: fresh input plus cache writes and reads."""
        u = self.usage
        return u["input_tokens"] + u["cache_creation_input_tokens"] + u["cache_read_input_tokens"]


# --- Grading -------------------------------------------------------------------------


def _regex(pattern: str, flags: str = "") -> re.Pattern:
    value = 0
    for flag, bit in (("i", re.IGNORECASE), ("m", re.MULTILINE), ("s", re.DOTALL)):
        if flag in flags:
            value |= bit
    return re.compile(pattern, value)


def grade(grader: Grader, transcript: Transcript, read_file, run_check, created: list[str]) -> tuple[bool, str]:
    o = grader.options
    if grader.type == "regex":
        target = o.get("target", "last_message")
        if isinstance(target, dict) and target.get("source") == "file":
            text = read_file(target["path"])
            if text is None:
                return False, f"{target['path']} does not exist"
        elif target == "trace":
            text = "\n".join(json.dumps(line) for line in transcript.lines)
        elif target == "files":
            text = "\n".join(created)
        else:
            text = transcript.final
        pattern = str(o.get("pattern") or grader.body)
        count = len(_regex(pattern, str(o.get("flags", ""))).findall(text))
        match = str(o.get("match", "contains"))
        if match == "not_contains":
            return count == 0, f"{count} match(es), expected none"
        if match.startswith("count:"):
            return count == int(match[6:]), f"{count} match(es), expected {match[6:]}"
        return count > 0, "found" if count else "pattern not found"
    if grader.type == "tool_used":
        wanted = str(o.get("tool"))
        matcher = _regex(str(o["input_match"])) if o.get("input_match") else None
        count = sum(
            1 for name, data in transcript.tool_calls
            if name == wanted and (matcher is None or matcher.search(json.dumps(data)))
        )  # fmt: skip
        low, high = int(o.get("min", 1)), o.get("max")
        ok = count >= low and (high is None or count <= int(high))
        return ok, f"{wanted} called {count} time(s)"
    if grader.type == "file_exists":
        hit = any(fnmatch.fnmatch(path, str(o["path"])) for path in created)
        want = o.get("exists", True)
        return hit == want, f"{o['path']} {'created' if hit else 'not created'}"
    if grader.type == "check":
        code, output = run_check(o["script"])
        return code == 0, output.strip().splitlines()[-1] if output.strip() else f"exit {code}"
    return False, f"grader type {grader.type!r} is not supported by this runner"


def score(results: list[dict], graders: list[Grader], two_arms: bool) -> float:
    scored = [(g, r) for g, r in zip(graders, results, strict=True) if not (two_arms and g.arm == "with-only")]
    if not scored:
        scored = list(zip(graders, results, strict=True))
    total = sum(g.weight for g, _ in scored)
    return sum(g.weight for g, r in scored if r["passed"]) / total if total else 0.0


# --- Docker ------------------------------------------------------------------------------


def docker(*args: str, input_text: str | None = None, timeout: float = 120, env=None) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["docker", *args],
        input=input_text,
        capture_output=True,
        text=True,
        timeout=timeout,
        check=False,
        env=env,
        encoding="utf-8",
        errors="replace",
    )


def image_tag() -> str:
    """Tag from the content that goes into the image, so any change to it rebuilds."""
    digest = hashlib.sha256()
    for path in sorted([HERE / "Dockerfile", *(REPO / "src").rglob("*"), *(REPO / "plugin").rglob("*")]):
        if path.is_file() and "__pycache__" not in path.parts:
            digest.update(str(path.relative_to(REPO)).encode())
            digest.update(path.read_bytes())
    return f"ctk-bench:{digest.hexdigest()[:12]}"


def claude_version() -> str:
    done = subprocess.run(
        ["claude", "--version"], capture_output=True, text=True, check=False, encoding="utf-8", errors="replace"
    )
    match = re.search(r"\d+\.\d+\.\d+", done.stdout)
    return match.group(0) if match else "stable"


def build_image(tag: str, rebuild: bool) -> None:
    if not rebuild and docker("image", "inspect", tag).returncode == 0:
        return
    args = ["build", "-q", "-f", str(HERE / "Dockerfile"), "--build-arg", f"CLAUDE_VERSION={claude_version()}"]
    args += ["-t", tag, str(REPO)]
    print(f"building {tag} …", file=sys.stderr)
    done = docker(*args, timeout=1800)
    if done.returncode != 0 and "buildx" in done.stderr:
        done = docker(*args, timeout=1800, env={**os.environ, "DOCKER_BUILDKIT": "0"})
    if done.returncode != 0:
        raise SystemExit(f"docker build failed:\n{done.stderr[-2000:]}")


def load_credentials() -> dict[str, str]:
    found = {}
    env_file = HERE / ".env"
    if env_file.exists():
        for line in env_file.read_text(encoding="utf-8").splitlines():
            name, sep, value = line.strip().partition("=")
            if sep and name in CREDENTIALS and value.strip():
                found[name] = value.strip().strip("\"'")
    for name in CREDENTIALS:
        if os.environ.get(name):
            found.setdefault(name, os.environ[name])
    return found


@dataclass
class RunResult:
    case: str
    arm: str
    index: int
    score: float
    graders: list[dict]
    context_tokens: int
    output_tokens: int
    usage: dict
    cost: float
    turns: int
    seconds: float
    error: str | None
    transcript: str


def run_once(case: Case, arm: str, index: int, args, tag: str, credentials: dict, out_dir: Path) -> RunResult:
    name = f"ctk-bench-{os.getpid()}-{case.name}-{arm}-{index}"
    env = {**os.environ, **credentials}
    creds = [flag for key in credentials for flag in ("-e", key)]
    started = time.monotonic()
    error = None
    try:
        made = docker("run", "-d", "--name", name, f"--memory={args.memory}", f"--cpus={args.cpus}",
                      *creds, tag, "sleep", "infinity", env=env)  # fmt: skip
        if made.returncode != 0:
            raise RuntimeError(made.stderr.strip())
        docker("cp", f"{case.path}/.", f"{name}:/case")
        if case.setup:
            setup = docker("exec", "-w", "/work", name, "bash", "/case/setup.sh", timeout=180)
            if setup.returncode != 0:
                raise RuntimeError(f"setup failed: {setup.stderr.strip()[-500:]}")
        # Both arms get a user CLAUDE.md, as real users have one: otherwise the bare arm alone would
        # reuse Claude Code's shared prompt cache and look cheaper than it is in practice.
        # The with arm is a real install: the plugin plus the section `ctk setup` adds to that file.
        docker(
            "exec",
            name,
            "sh",
            "-c",
            f"mkdir -p ~/.claude && printf '%s\\n' {shlex.quote(USER_CLAUDE_MD)} > ~/.claude/CLAUDE.md",
        )
        if arm == "with":
            snippet = "from claude_toolkit.setup import SNIPPET; print(); print(SNIPPET)"
            write = f"PYTHONPATH=/opt/ctk/src python3 -c '{snippet}' >> ~/.claude/CLAUDE.md"
            docker("exec", name, "sh", "-c", write)
        # Files newer than this marker were made by Claude.
        docker("exec", name, "sh", "-c", "sleep 1; touch /tmp/.ctk-bench-start")
        command = ["exec", "-w", "/work", name, "claude", "-p", case.prompt, "--output-format", "stream-json",
                   "--verbose", "--max-turns", str(case.max_turns), "--dangerously-skip-permissions"]  # fmt: skip
        if args.model:
            command += ["--model", args.model]
        if arm == "with":
            command += ["--plugin-dir", PLUGIN_IN_IMAGE]
        try:
            done = docker(*command, timeout=case.timeout, env=env)
            raw = done.stdout
            if done.returncode != 0 and not raw.strip():
                error = done.stderr.strip()[-500:] or f"claude exited {done.returncode}"
        except subprocess.TimeoutExpired as expired:
            raw = expired.stdout.decode() if isinstance(expired.stdout, bytes) else (expired.stdout or "")
            error = f"timed out after {case.timeout}s"
        transcript = Transcript.parse(raw)
        error = error or transcript.error
        listed = docker("exec", "-w", "/work", name, "sh", "-c",
                        "find . -path ./.git -prune -o -type f -newer /tmp/.ctk-bench-start -print")  # fmt: skip
        created = [line[2:] for line in listed.stdout.splitlines() if line.startswith("./")]

        def read_file(path: str) -> str | None:
            got = docker("exec", "-w", "/work", name, "cat", path)
            return got.stdout if got.returncode == 0 else None

        def run_check(script: str) -> tuple[int, str]:
            got = docker("exec", "-w", "/work", name, "bash", f"/case/checks/{script}", timeout=300)
            return got.returncode, got.stdout + got.stderr

        verdicts = []
        for grader in case.graders:
            passed, detail = grade(grader, transcript, read_file, run_check, created)
            verdicts.append({"name": grader.name, "type": grader.type, "passed": passed, "detail": detail})
    except (RuntimeError, subprocess.TimeoutExpired) as problem:
        transcript, verdicts, error, raw = Transcript([]), [], str(problem), ""
        verdicts = [{"name": g.name, "type": g.type, "passed": False, "detail": "not run"} for g in case.graders]
    finally:
        docker("rm", "-f", name)
    path = out_dir / case.name / f"{arm}-{index}.jsonl"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(raw, encoding="utf-8")
    two_arms = len(args.arms) == 2
    return RunResult(
        case=case.name, arm=arm, index=index, score=score(verdicts, case.graders, two_arms), graders=verdicts,
        context_tokens=transcript.context_tokens, output_tokens=transcript.usage.get("output_tokens", 0),
        usage=transcript.usage, cost=transcript.cost, turns=transcript.turns,
        seconds=round(time.monotonic() - started, 1), error=error, transcript=str(path.relative_to(HERE)),
    )  # fmt: skip


# --- Report ----------------------------------------------------------------------------------


def _mean(values: list[float]) -> float:
    return statistics.fmean(values) if values else 0.0


def summarise(results: list[RunResult], cases: list[Case], arms: list[str]) -> tuple[list[dict], str]:
    """Means over the runs that completed; runs with an error are counted, not scored."""
    rows = []
    for case in cases:
        row: dict = {"case": case.name}
        for arm in arms:
            every = [r for r in results if r.case == case.name and r.arm == arm]
            runs = [r for r in every if not r.error]
            row[arm] = {
                "score": round(_mean([r.score for r in runs]), 2),
                "context_tokens": round(_mean([r.context_tokens for r in runs])),
                "output_tokens": round(_mean([r.output_tokens for r in runs])),
                "cost": round(_mean([r.cost for r in runs]), 4),
                "turns": round(_mean([r.turns for r in runs]), 1),
                "errors": len(every) - len(runs),
                "runs": len(runs),
            }
        rows.append(row)
    header = (
        f"{'CASE':<22} {'ARM':<8} {'SCORE':>5} {'CONTEXT TOK':>12} {'OUT TOK':>8} {'TURNS':>6} {'COST $':>8} {'ERR':>4}"
    )
    lines = [header]
    for row in rows:
        for arm in arms:
            a = row[arm]
            lines.append(f"{row['case']:<22} {arm:<8} {a['score']:>5.2f} {a['context_tokens']:>12,} "
                         f"{a['output_tokens']:>8,} {a['turns']:>6} {a['cost']:>8.3f} {a['errors']:>4}")  # fmt: skip
        if len(arms) == 2:
            w, wo = row["with"], row["without"]
            change = (
                (w["context_tokens"] - wo["context_tokens"]) / wo["context_tokens"] * 100 if wo["context_tokens"] else 0
            )
            lines.append(f"{'':<22} {'Δ':<8} {w['score'] - wo['score']:>+5.2f} {change:>+11.0f}%")
    return rows, "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--case", help="only cases whose name matches this glob")
    parser.add_argument("--runs", type=int, help="runs per case and arm (default: the case's, else 3)")
    parser.add_argument("--arms", nargs="+", choices=("with", "without"), default=["with", "without"])
    parser.add_argument("--model", help="model for the agent under test (pin it to compare over time)")
    parser.add_argument("--memory", default="2g", help="memory limit per container (default 2g)")
    parser.add_argument("--cpus", default="2", help="CPU limit per container (default 2)")
    parser.add_argument("-j", "--concurrency", type=int, default=1, help="containers at once (default 1)")
    parser.add_argument("--rebuild", action="store_true", help="rebuild the image even if it exists")
    parser.add_argument("--list", action="store_true", help="list cases and exit")
    args = parser.parse_args(argv)

    cases = find_cases(args.case)
    if args.list or not cases:
        for case in cases:
            print(f"{case.name}: {len(case.graders)} grader(s), {case.runs} run(s)")
        return 0 if cases else 1
    if not shutil.which("docker"):
        print("benchmark: docker is required", file=sys.stderr)
        return 1
    credentials = load_credentials()
    if not credentials:
        print(
            f"benchmark: no credentials; copy {HERE / '.env.example'} to benchmark/.env and fill it in", file=sys.stderr
        )
        return 2
    tag = image_tag()
    build_image(tag, args.rebuild)
    out_dir = RESULTS / time.strftime("%Y%m%d-%H%M%S")
    jobs = [(case, arm, i) for case in cases for arm in args.arms for i in range(1, (args.runs or case.runs) + 1)]
    print(f"{len(jobs)} run(s) on {tag} → {out_dir.relative_to(REPO)}", file=sys.stderr)

    def job(item):
        case, arm, index = item
        result = run_once(case, arm, index, args, tag, credentials, out_dir)
        failed = [g["name"] for g in result.graders if not g["passed"]]
        print(f"  {case.name} {arm} #{index}: score {result.score:.2f} · {result.context_tokens:,} ctx tok · "
              f"${result.cost:.3f}" + (f" · failed: {', '.join(failed)}" if failed else "")
              + (f" · error: {result.error}" if result.error else ""), file=sys.stderr)  # fmt: skip
        return result

    results: list[RunResult] = []
    stopped = None
    with ThreadPoolExecutor(max_workers=max(1, args.concurrency)) as pool:
        pending = [pool.submit(job, item) for item in jobs]
        for future in pending:
            if stopped:
                future.cancel()
                continue
            result = future.result()
            results.append(result)
            if result.error and LIMIT_ERRORS.search(result.error):
                stopped = result.error
                print(f"benchmark: stopping, the account hit a limit: {stopped}", file=sys.stderr)
    rows, table = summarise(results, cases, args.arms)
    (out_dir / "results.json").write_text(json.dumps(
        {"image": tag, "model": args.model, "arms": args.arms, "partial": stopped, "summary": rows,
         "runs": [asdict(r) for r in results]},
        indent=2,
    ), encoding="utf-8")  # fmt: skip
    (out_dir / "summary.txt").write_text(table + "\n", encoding="utf-8")
    print(table)
    if stopped:
        print(f"partial results: {stopped}", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
