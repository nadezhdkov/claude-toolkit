<div align="center">

<img src="../../assets/logo.jpg" alt="claude-toolkit-Logo" width="150">

# claude-toolkit

**Allgemeine Werkzeuge, Hooks, Skills und Subagenten, die Claude Code in jedem Projekt wirksamer machen.**

[![CI](https://github.com/nadezhdkov/claude-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/nadezhdkov/claude-toolkit/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/tag/nadezhdkov/claude-toolkit?label=version&color=38bdf8&sort=semver)](../../CHANGELOG.md)
[![License: MIT](https://img.shields.io/github/license/nadezhdkov/claude-toolkit?color=94a3b8)](../../../LICENSE)

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-toolkit-d97757?logo=anthropic&logoColor=white)](https://docs.claude.com/en/docs/claude-code)
[![uv](https://img.shields.io/badge/uv-managed-de5fe9?logo=uv&logoColor=white)](https://docs.astral.sh/uv/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Runtime deps: none](https://img.shields.io/badge/runtime%20deps-none-22c55e)](../../../pyproject.toml)
[![Installer: POSIX sh](https://img.shields.io/badge/installer-POSIX%20sh-4EAA25?logo=gnubash&logoColor=white)](../../../install.sh)

[Warum](#warum) · [Installation](#installation) · [Befehle](#befehle) · [Roadmap](../../roadmap.md) · [Design](../../design.md) · [Mitwirken](../../../CONTRIBUTING.md)

**Sprachen:** [English](../../../README.md) · [Português (Brasil)](../pt-BR/README.md) · [Español](../es/README.md) · **Deutsch** · [简体中文](../zh-CN/README.md)

</div>

---

> Übersetzung der [englischen README](../../../README.md), die maßgeblich ist. Die Seiten zu den einzelnen Befehlen, das Design, die Roadmap und das Changelog bleiben auf Englisch.

## Warum

KI-Programmieragenten verlieren in fast jedem Projekt an denselben Stellen Zeit
und machen dort dieselben Fehler. claude-toolkit nimmt sich vier davon vor,
jeweils an echten Claude-Code-Sitzungen gemessen:

| Problem | Beispiel | Werkzeug |
|---|---|---|
| Builds und Tests scheitern an der Umgebung | Node 26 installiert, obwohl das Repository 24 festlegt; `node_modules` fehlt | `ctk doctor` |
| Lange Befehlsausgaben überfluten das Kontextfenster | Tausende Testzeilen, um drei Fehlschläge zu finden | `ctk runq` |
| Code-Navigation per grep statt über Definitionen | Dutzende Dateizugriffe, um ein Muster zu finden | `ctk lsp` |
| Keine Möglichkeit festzustellen, ob eine Änderung geholfen hat | „Es fühlt sich schneller an“ | `ctk sessions` |

Alle Werkzeuge folgen denselben Regeln: Sie sind **schnell**, **still, wenn
alles in Ordnung ist**, und **ändern dein System nie, ohne zu fragen**. Ohne
Terminal (zum Beispiel, wenn Claude sie ausführt) gibt eine Änderung ihren Plan
aus und endet mit dem Code `3`; eine Person genehmigt sie und führt sie erneut
mit `--yes` aus.

Die Ausgabe ist **für Menschen gestaltet und für Agenten schlicht**: Farben,
Diagramme und ein Fortschritts-Spinner erscheinen nur in einem interaktiven
Terminal; Pipes, Logs und Claude Code erhalten kompakten Klartext. `NO_COLOR`
schaltet die Farben ab, `FORCE_COLOR` schaltet sie ein.

## Installation

Voraussetzungen: Linux, macOS oder Windows (mit Git Bash), `git` und [uv](https://docs.astral.sh/uv/)
(der Installer bietet an, uv zu installieren, falls es fehlt). Der Befehl `ctk`
hat zur Laufzeit keine Abhängigkeiten außer Python 3.11+.

```bash
git clone https://github.com/nadezhdkov/claude-toolkit.git
cd claude-toolkit
./install.sh            # shows the plan, asks before each step
```

Unter Windows in PowerShell: `.\install.ps1` (gleicher Plan und gleiche Fragen; `-Yes`, `-DryRun`).

Der Installer führt `uv tool install --editable .` aus (damit `git pull` `ctk`
aktualisiert) und danach `ctk setup`. Dieses fügt `~/.claude/CLAUDE.md` einen
kurzen Abschnitt hinzu, der Claude Code sagt, wann welcher Befehl zu verwenden
ist (mit Sicherung), und bietet an, fehlende optionale Abhängigkeiten zu
installieren. Manuelle Schritte, Aktualisieren und Deinstallieren stehen in
[installation.md](installation.md).

## Befehle

Führe `ctk` allein aus, um eine Übersicht zu erhalten:

<img src="../../assets/screenshots/overview.svg" alt="ctk-Übersicht mit Befehlen und Beispielen">

| Befehl | Was er tut |
|---|---|
| [`ctk doctor`](../../commands/doctor.md) | Festgelegte Toolchain-Versionen gegen installierte, Abhängigkeiten gegen Lockfiles |
| [`ctk runq`](../../commands/runq.md) | Führt einen Befehl aus; gibt Fehlschläge, die Zusammenfassung und den Pfad des vollständigen Logs aus |
| [`ctk lsp`](../../commands/lsp.md) | Language Server und LSP-Plugins für Claude Code, die ein Projekt braucht |
| [`ctk sessions`](../../commands/sessions.md) | Reine Zählwerte aus den Transkripten von Claude Code |
| [`ctk shoot`](../../commands/shoot.md) | Deterministische Screenshots von Webseiten, Godot-Szenen und Desktop-Anwendungen; Baselines und Kontaktbögen |
| [`ctk audiocheck`](../../commands/audiocheck.md) | Lautheit, Clipping, Stille und Loop-Nähte von Audiodateien, mit Wellenform- und Spektrogramm-Bildern |
| [`ctk sandbox`](../../commands/sandbox.md) | Führt nicht vertrauenswürdigen Code ohne Netzwerk aus, mit schreibgeschütztem System, leerem Home-Verzeichnis und Ressourcenlimits |
| [`ctk libdocs`](../../commands/libdocs.md) | Installierte Version, deklarierte Einschränkung, README und API einer Abhängigkeit; wo ein Symbol definiert ist |
| [`ctk map`](../../commands/map.md) | Kompakte Karte der Dateien und zentralen Symbole eines Repositorys; wo ein Symbol verwendet wird und welche Tests es berühren |
| [`ctk verify`](../../commands/verify.md) | Was für den Code in seinem jetzigen Zustand verifiziert ist: jeder `runq`-Lauf pro Code-Zustand erfasst; aktuell, fehlgeschlagen, veraltet oder nie ausgeführt |
| [`ctk diffcheck`](../../commands/diffcheck.md) | Deterministische Prüfungen einer Änderung: entfernte API, die noch verwendet wird, riskante Dateien, Debug-Reste, Code ohne Tests |
| [`ctk relay`](../../commands/relay.md) | Übergibt die Arbeit in einem neuen Terminal an eine frische Claude-Code-Sitzung, ausgehend von der Handoff-Datei und dem verifizierten Zustand |
| [`ctk setup`](installation.md) | Bindet das Toolkit in Claude Code ein und fragt vor jeder Änderung |
| [`ctk hook`](../../commands/hooks.md) | Die Logik hinter den Plugin-Hooks (Ereignis-JSON auf der Standardeingabe) |

### `ctk doctor` — Umgebungsprüfung

Vergleicht die festgelegte Toolchain eines Projekts (`.nvmrc`, `.node-version`,
`engines` und `packageManager` in `package.json`, `.python-version`,
`requires-python`, `go.mod`, `rust-toolchain`, `.tool-versions`) mit dem, was
installiert ist, und prüft, ob die Abhängigkeiten zum Lockfile passen.

<img src="../../assets/screenshots/doctor.svg" alt="Ausgabe von ctk doctor: Probleme mit Node-Version und Lockfile samt Lösungen">

`ctk doctor --toolkit` prüft die eigenen Abhängigkeiten des Toolkits, mit
Installationsbefehlen für deine Distribution.

### `ctk runq` — Befehlsausgabe ohne Rauschen

Führt einen Befehl aus, speichert die vollständige Ausgabe in einem Log und gibt
nur die Fehlschläge, die Zusammenfassung und den Log-Pfad aus. Kurze Ausgaben
werden unverändert ausgegeben, und der Exit-Code bleibt immer erhalten. Erkennt
pytest, vitest/jest, tsc, ruff/eslint, cargo, go test und gradle, mit einem
allgemeinen Fallback für alles andere.

<img src="../../assets/screenshots/runq.svg" alt="Ausgabe von ctk runq: fehlgeschlagene Tests hervorgehoben, mit Exit-Code, Dauer und Log-Pfad">

### `ctk lsp` — Language Server

Erkennt die Sprachen des Projekts und meldet, ob jede ihr Language-Server-Binary
und ihr offizielles LSP-Plugin für Claude Code hat; `--install` installiert die
fehlenden Teile und fragt vor jedem einzelnen.

<img src="../../assets/screenshots/lsp.svg" alt="Ausgabe von ctk lsp: Sprachen mit Status von Server und Plugin und Installationsbefehlen">

### `ctk sessions` — messen, was hilft

Liest die Transkripte von Claude Code (`~/.claude/projects`) und meldet **nur
Zählwerte**: Werkzeugaufrufe und Fehler, Erkundung vor der ersten Änderung,
Größen von Befehlsausgaben, Hinweise „Datei auf der Festplatte geändert“ sowie
die Nutzung von Skills, Subagenten, MCP-Servern und `ctk`. `--csv -` gibt
Wochenzeilen für Vorher-nachher-Vergleiche aus. Der Text der Nachrichten wird
nie kopiert.

<img src="../../assets/screenshots/sessions.svg" alt="Ausgabe von ctk sessions: Aktivität, Kontextnutzung und ein Balkendiagramm der meistgenutzten Werkzeuge">

### `ctk shoot`: sehen, was sich geändert hat

Deterministische Screenshots, damit Claude die Oberfläche ansehen kann, die es
gerade geändert hat: Webseiten über das Chromium von Playwright (eingefrorene
Animationen, feste Viewport-Größe, Zeitzone und Sprache), Godot-4-Szenen über
den Movie Writer und beliebige Desktop-Programme auf einem privaten
Xvfb-Display. `--baseline` vergleicht mit einem Referenzbild, mit Schwellwert,
Toleranz und Masken, und schreibt ein Differenzbild mit dem Begrenzungsrahmen
der Änderung. `ctk shoot sheet` fasst mehrere Aufnahmen zu einem nummerierten
Kontaktbogen zusammen.

```bash
ctk shoot web localhost:5173 --baseline shots/home.png
ctk shoot godot . --scene res://ui/menu.tscn
```

### `ctk audiocheck`: Probleme hören, ohne zuzuhören

Misst die Lautheit (EBU R128) und den True Peak, findet Clipping (auch wenn es
danach abgeschwächt wurde), stumme Dateien, Stille an den Rändern und
DC-Offset und erkennt mit `--loop` Knackser am Loop-Punkt. `--images` schreibt
pro Datei eine Wellenform und ein Spektrogramm.

```bash
ctk audiocheck assets/audio --target -16 --images
```

### `ctk sandbox`: nicht vertrauenswürdigen Code sicher ausführen

Führt einen Befehl mit bubblewrap aus: kein Netzwerk, das System schreibgeschützt,
ein leeres Home-Verzeichnis (keine SSH-Schlüssel oder Tokens), nur das
Projektverzeichnis beschreibbar, eine geleerte Umgebung sowie Limits für
Speicher, CPU, Prozesse und Zeit.

```bash
ctk sandbox -- npm test
ctk sandbox --dir ~/src/unknown-repo --timeout 300 -- make
```

### `ctk libdocs`: die API, die du tatsächlich hast

Liest eine Abhängigkeit aus ihren installierten Dateien (Python, Node, Rust, Go)
und zeigt die installierte Version neben der deklarierten Einschränkung, das
README und die öffentliche API; `--find` gibt die Definition eines Symbols mit
Signatur und Dokumentation aus. Vom Paket wird nichts importiert oder
ausgeführt.

```bash
ctk libdocs pydantic --find BaseModel.model_dump
```

## Hooks-Plugin

Das Claude-Code-Plugin `ctk` fügt Hooks hinzu, die außerhalb der Unterhaltung
laufen und keinen Kontext kosten. Sie bleiben still, wenn alles in Ordnung ist,
und überspringen Projekte, auf die sie nicht zutreffen:

| Hook | Was er tut |
|---|---|
| `format-file` | formatiert die Datei, die Claude gerade bearbeitet hat, mit dem Formatierer des Projekts selbst (ruff, black, prettier, biome, rustfmt, gofmt, stylua, clang-format) |
| `affected-tests` | führt am Ende eines Zugs die Tests aus, die zu den bearbeiteten Dateien gehören; bei Fehlschlägen arbeitet Claude mit der Zusammenfassung weiter |
| `guard-destructive` | markiert `rm -rf` außerhalb des Projekts, Force-Push auf `main` und `git reset --hard` über nicht committeter Arbeit (nur Warnung, bis du auf Blockieren umstellst) |
| `secrets` | führt vor `git commit` `gitleaks` aus und lehnt Commits mit Geheimnissen ab |
| `notify` | Desktop-Benachrichtigung, wenn Claude Code auf dich wartet oder ein langer Zug endet |

`ctk setup` installiert es und fragt vorher; von Hand:

```bash
claude plugin marketplace add nadezhdkov/claude-toolkit
claude plugin install ctk@ctk
```

Einstellungen pro Projekt und das Abschalten stehen in `.claude-toolkit.toml`;
siehe [docs/commands/hooks.md](../../commands/hooks.md).

## Skills

Das Plugin liefert auch Prozess-Skills mit, die Claude lädt, wenn eine Aufgabe
passt, oder die du als `/ctk:<name>` aufrufst: `debug` (Ursache vor der
Korrektur), `ship` (Prüfungen, Review, PR), `handoff` (Fortschrittsdatei über
Sitzungen hinweg), `onboard-repo`, `visual-qa` (Screenshots ansehen, bevor die
Oberflächenarbeit als fertig gilt) und `security-pass`. Sie weichen dem
eigenen Prozess eines Projekts, wenn es einen gibt. Siehe [docs/skills.md](../../skills.md).

## Subagenten

`ctk:test-runner`, `ctk:reviewer` und `ctk:researcher` nehmen laute oder
unabhängige Arbeit aus der Hauptunterhaltung und liefern kurze Berichte, die mit
einem Urteil enden (`pass`/`fail`, `approve`/`changes-requested`,
`answered`/`not-found`), belegt durch `Pfad:Zeile` oder URL. Ein Hook erzwingt
diese Ausgabeverträge, und die Skill `orchestrate` sagt, wann delegiert wird,
und führt den Zyklus implementieren → testen → prüfen aus. Siehe
[docs/agents.md](../../agents.md).

## Benchmark

`benchmark/run.py` führt feste Aufgaben mit und ohne das Plugin aus, jede in
einem sauberen Docker-Container, und vergleicht Punktzahl, Kontext-Tokens, Züge
und Kosten. Siehe [benchmark/README.md](../../../benchmark/README.md).

## Roadmap

`0.1.0` lieferte die Grundlage: `doctor`, `runq`, `lsp`, `sessions` und den
Installer; danach kamen das Plugin mit den Qualitäts-Hooks, `ctk shoot`,
`ctk audiocheck` und die Prozess-Skills, `ctk sandbox`, `ctk libdocs` sowie
Subagenten mit erzwungenen Ausgabeverträgen. Siehe [docs/roadmap.md](../../roadmap.md).

## Entwicklung

```bash
uv sync                                               # dev environment
uv run ruff check . && uv run ruff format --check .   # lint and format
uv run pytest                                         # tests
uv run ctk doctor                                     # run the CLI from the checkout
```

Pull Requests führen Lint, shellcheck, Tests auf Python 3.11–3.13, einen
Installations-Smoke-Test, eine Prüfung des Titels nach Conventional Commits und
eine Changelog-Prüfung aus; die Maintainer mergen mit dem Label `automerge`.
Siehe [CONTRIBUTING.md](../../../CONTRIBUTING.md) und [AGENTS.md](../../../AGENTS.md).

## Lizenz

[MIT](../../../LICENSE)
