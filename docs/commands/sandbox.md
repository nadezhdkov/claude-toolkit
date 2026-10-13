# `ctk sandbox`

Runs a command in a [bubblewrap](https://github.com/containers/bubblewrap)
sandbox: for untrusted code, unknown repositories' tests and build scripts,
downloaded tools and anything an agent should not let loose on the machine.

```bash
ctk sandbox -- npm test                          # current directory, no network
ctk sandbox --dir ~/src/unknown-repo -- make     # another directory
ctk sandbox --net -- uv sync                     # allow network
ctk sandbox --read-only -- ./analyse.sh          # the directory cannot be modified
ctk sandbox --memory 1G --cpus 1 --timeout 120 -- python script.py
ctk sandbox --dry-run -- cargo build             # show what would be mounted and the bwrap command
```

## What the command sees

| Path | Access |
|---|---|
| `/usr`, `/etc`, `/opt` and the `/bin`, `/lib`… links | read-only |
| the target (`--dir`, default `.`) at its real path | read-write (`--read-only` to forbid writes) |
| the home directory | an empty tmpfs: no `~/.ssh`, `~/.config`, tokens, browser profiles… |
| toolchains under the home (`~/.local/bin`, uv's Pythons, `~/.cargo/bin`, `~/.rustup/toolchains`, nvm/fnm/volta/bun/deno/pyenv/mise/sdkman installs) | read-only, so projects still build; `--no-toolchains` hides them. Credential files such as `~/.cargo/credentials.toml` or `~/.npmrc` are never mounted |
| `/tmp`, `/run`, `/var` | private tmpfs, size-capped (see below) |
| `--ro PATH`, `--rw PATH` | extra mounts |

- **Network:** none, not even DNS (only a private loopback); `--net` shares the host's.
- **Environment:** cleared; only `PATH`, locale, terminal and colour variables, `HOME`,
  `TMPDIR` and `CTK_SANDBOX=1` are set. `--env NAME[=VALUE]` passes more. Tokens in the
  parent's environment do not leak in.
- **Processes:** new PID, IPC, UTS, user and cgroup namespaces, all capabilities
  dropped, a new session (no terminal injection), killed when `ctk` exits.
- **Limits:** memory (`--memory`, no swap), CPU (`--cpus`, default 2),
  processes (`--pids`, default 512) through a systemd user scope (cgroups v2).
  The default memory limit is **half the machine's RAM, at most 4G** (at least
  256M), so a sandboxed build cannot starve a small machine.
- **RAM used by tmpfs:** `/tmp` and the empty home are tmpfs, which live in RAM.
  Each is capped at **an eighth of the RAM, at most 1G** (`--tmp-size`); `/run`
  and `/var` at 64M. A command that fills them gets "No space left on device"
  instead of eating memory, and the cap holds even without a systemd scope.
  Without a systemd user session they cannot be enforced and the command says so
  on stderr; the timeout (`--timeout`, default 600 s) always applies and stops the
  whole process tree.

`ctk sandbox` refuses to mount the home directory itself or `/`, and never runs
the command unsandboxed when bubblewrap is missing or cannot create namespaces.

## Project defaults

```toml
# .claude-toolkit.toml
[sandbox]
memory = "8G"
tmp-size = "2G"
cpus = 4
timeout = 1800
net = false
ro = ["~/datasets"]
```

Command-line flags win over the file.

## Exit codes

The command's own exit code; `124` on timeout; `137` or `143` when killed by
the memory limit (SIGKILL from the kernel, or SIGTERM when systemd stops the
scope; the reason is printed on stderr); `1` when the sandbox cannot be set up
(the command did not run); `2` for usage errors.

## Requirements

Linux with `bwrap` (`ctk doctor --toolkit` shows the install command) and
unprivileged user namespaces. On Ubuntu 24.04+ AppArmor restricts them; the
error message gives the `sysctl` to change or the AppArmor profile route.
Resource limits need `systemd-run --user` (a normal desktop or SSH session has it).

## Done criteria (tested in `tests/test_sandbox.py`)

- No network (only `lo`), an empty home (a file in the real home is invisible), a
  read-only system, a writable target, and the exit code preserved.
- Only toolchain directories are mounted from the home, never credential files;
  the environment is cleared (a token in the parent environment is not passed).
- Memory and tmpfs defaults scale down with the machine's RAM; every tmpfs is
  size-capped, and filling `/tmp` fails instead of using more RAM.
- `--read-only` blocks writes; `--timeout` exits `124`; with a systemd scope, a
  memory-hungry command is killed (`137`), otherwise the missing limits are reported.
  The real kill runs only with `CTK_TEST_OOM=1`, because desktop sessions announce
  every out-of-memory kill with a notification.
- Without bubblewrap the command is never run.
