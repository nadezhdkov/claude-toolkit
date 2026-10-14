# Installation

> Übersetzung von [installation.md](../../installation.md), das maßgeblich ist. [README](README.md) · **Sprachen:** [English](../../installation.md) · [Português (Brasil)](../pt-BR/installation.md) · [Español](../es/installation.md) · **Deutsch** · [简体中文](../zh-CN/installation.md)

## Schnellinstallation

```bash
git clone https://github.com/nadezhdkov/claude-toolkit.git
cd claude-toolkit
./install.sh
```

`install.sh` gibt seinen Plan aus und fragt vor jedem Schritt:

1. installiert [uv](https://docs.astral.sh/uv/) mit dem offiziellen Installer, falls es fehlt;
2. führt `uv tool install --editable <repo>` aus, was `ctk` nach `~/.local/bin` legt;
3. führt `ctk setup` aus.

Optionen: `--dry-run` gibt nur den Plan aus; `--yes` beantwortet jede Frage mit
Ja (nur verwenden, nachdem du den Plan gelesen hast). Ohne Terminal und ohne
`--yes` bricht der Installer mit dem Exit-Code `3` ab, bevor er etwas ändert.

Wenn `~/.local/bin` nicht in deinem `PATH` liegt, führe `uv tool update-shell`
aus und starte die Shell neu.

## Manuelle Installation

```bash
uv tool install --editable /path/to/claude-toolkit
ctk setup
```

## Was `ctk setup` ändert

`ctk setup` erstellt einen Plan, gibt ihn aus und wendet jeden Schritt erst an,
nachdem du ihn bestätigt hast:

| Schritt | Änderung | Rückgängig machen |
|---|---|---|
| Anweisungen für Claude Code | Fügt am Ende von `~/.claude/CLAUDE.md` einen kurzen Abschnitt zwischen `<!-- claude-toolkit:start -->` und `<!-- claude-toolkit:end -->` hinzu (oder aktualisiert ihn), damit Claude Code weiß, wann welcher `ctk`-Befehl zu verwenden ist. Die vorherige Datei wird nach `~/.claude/backups/claude-toolkit/` gesichert. | `ctk setup --uninstall` |
| Hooks-Plugin | Registriert dieses Repository als Plugin-Marketplace `ctk` und installiert das Plugin `ctk` (`claude plugin marketplace add`, `claude plugin install ctk@ctk`). Siehe [Hooks](../../commands/hooks.md). | `ctk setup --uninstall` |
| Optionale Abhängigkeiten | Bietet an, fehlende Werkzeuge zu installieren, die `ctk doctor --toolkit` auflistet (zum Beispiel `gitleaks`, `Xvfb`), mit dem Paketmanager deiner Distribution. | dein Paketmanager |
| Andere Agenten (optional) | Wird Codex, Gemini CLI oder opencode gefunden, oder mit `--agents`: kopiert die Prozess-Skills nach `~/.agents/skills/` (nie über eine eigene Skill). `--agents-file DATEI` fügt denselben kurzen Abschnitt einer globalen Anweisungsdatei hinzu, die du angibst. | `ctk setup --uninstall` (für die Datei `--agents-file DATEI` erneut angeben) |

`ctk setup` erneut auszuführen ist unbedenklich: Es schlägt nur vor, was fehlt oder veraltet ist.

## Aktualisieren

```bash
cd /path/to/claude-toolkit
git pull
ctk setup        # refreshes the CLAUDE.md section if it changed
```

Durch die editierbare Installation aktualisiert `git pull` `ctk` sofort.

## Deinstallieren

```bash
ctk setup --uninstall      # removes the CLAUDE.md section (with a backup) and the plugin
uv tool uninstall claude-toolkit
```

Die Logs von `ctk runq` und den Hooks liegen in `~/.cache/claude-toolkit/` und können gelöscht werden.

## Unterstützte Systeme

Linux (Arch-basiert, Debian/Ubuntu, Fedora, openSUSE), macOS und Windows; die
CI testet alle drei. Die Installationshinweise richten sich nach dem erkannten
Paketmanager; andere Systeme erhalten allgemeine Hinweise.

### Windows

Installiere mit `.\install.ps1` in PowerShell (`-Yes`, `-DryRun`; Exit-Code `3`,
wenn eine Genehmigung nötig ist und kein Terminal vorhanden ist, wie bei
`install.sh`). Das Plugin braucht [Git for Windows](https://git-scm.com): Claude
Code führt Hooks in Git Bash aus, und ohne Git Bash hat Claude Code kein
Bash-Werkzeug, das die Skills und Agenten des Plugins zum Ausführen von `ctk`
verwenden. Einige Befehle bleiben Linux-only: `ctk sandbox` (bubblewrap) und
`ctk shoot desktop` (Xvfb).
