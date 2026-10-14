# Installation

**Languages:** **English** · [Português (Brasil)](i18n/pt-BR/installation.md) · [Español](i18n/es/installation.md) · [Deutsch](i18n/de/installation.md) · [简体中文](i18n/zh-CN/installation.md)

## Quick install

```bash
git clone https://github.com/nadezhdkov/claude-toolkit.git
cd claude-toolkit
./install.sh
```

`install.sh` prints its plan and asks before each step:

1. installs [uv](https://docs.astral.sh/uv/) with the official installer if it is missing;
2. runs `uv tool install --editable <repo>`, which puts `ctk` in `~/.local/bin`;
3. runs `ctk setup`.

Options: `--dry-run` prints the plan only; `--yes` answers yes to every
question (use it only after reading the plan). Without a terminal and without
`--yes`, the installer stops with exit code `3` before changing anything.

If `~/.local/bin` is not on your `PATH`, run `uv tool update-shell` and restart
the shell.

## Manual install

```bash
uv tool install --editable /path/to/claude-toolkit
ctk setup
```

## What `ctk setup` changes

`ctk setup` builds a plan, prints it, and applies each step only after you
confirm it:

| Step | Change | Undo |
|---|---|---|
| Claude Code instructions | Adds (or refreshes) a short section between `<!-- claude-toolkit:start -->` and `<!-- claude-toolkit:end -->` at the end of `~/.claude/CLAUDE.md`, so Claude Code knows when to use each `ctk` command. The previous file is backed up to `~/.claude/backups/claude-toolkit/`. | `ctk setup --uninstall` |
| Hooks plugin | Registers this repository as the `ctk` plugin marketplace and installs the `ctk` plugin (`claude plugin marketplace add`, `claude plugin install ctk@ctk`). See [hooks](commands/hooks.md). | `ctk setup --uninstall` |
| Optional dependencies | Offers to install missing tools listed by `ctk doctor --toolkit` (for example `gitleaks`, `Xvfb`) with your distribution's package manager. | your package manager |

Running `ctk setup` again is safe: it only proposes what is missing or outdated.

## Updating

```bash
cd /path/to/claude-toolkit
git pull
ctk setup        # refreshes the CLAUDE.md section if it changed
```

The editable install means `git pull` updates `ctk` immediately.

## Uninstalling

```bash
ctk setup --uninstall      # removes the CLAUDE.md section (with a backup) and the plugin
uv tool uninstall claude-toolkit
```

Logs written by `ctk runq` and the hooks live in `~/.cache/claude-toolkit/` and can be deleted.

## Supported systems

Linux (Arch-based, Debian/Ubuntu, Fedora, openSUSE), macOS and Windows; CI
tests all three. Install hints are tailored to the detected package manager;
other systems get generic hints.

### Windows

Install with `.\install.ps1` in PowerShell (`-Yes`, `-DryRun`; exit `3` when it
needs approval and has no terminal, like `install.sh`). The plugin needs
[Git for Windows](https://git-scm.com): Claude Code runs hooks in Git Bash,
and without it Claude Code has no Bash tool, which the plugin's skills and
agents use to run `ctk`. A few commands stay Linux-only: `ctk sandbox`
(bubblewrap) and `ctk shoot desktop` (Xvfb).
