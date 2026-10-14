# Instalación

> Traducción de [installation.md](../../installation.md), que es la fuente de verdad. [README](README.md) · **Idiomas:** [English](../../installation.md) · [Português (Brasil)](../pt-BR/installation.md) · **Español** · [Deutsch](../de/installation.md) · [简体中文](../zh-CN/installation.md)

## Instalación rápida

```bash
git clone https://github.com/nadezhdkov/claude-toolkit.git
cd claude-toolkit
./install.sh
```

`install.sh` muestra su plan y pregunta antes de cada paso:

1. instala [uv](https://docs.astral.sh/uv/) con el instalador oficial si falta;
2. ejecuta `uv tool install --editable <repo>`, que pone `ctk` en `~/.local/bin`;
3. ejecuta `ctk setup`.

Opciones: `--dry-run` solo muestra el plan; `--yes` responde que sí a todas las
preguntas (úsalo solo después de leer el plan). Sin terminal y sin `--yes`, el
instalador se detiene con el código de salida `3` antes de cambiar nada.

Si `~/.local/bin` no está en tu `PATH`, ejecuta `uv tool update-shell` y
reinicia el shell.

## Instalación manual

```bash
uv tool install --editable /path/to/claude-toolkit
ctk setup
```

## Qué cambia `ctk setup`

`ctk setup` construye un plan, lo muestra y aplica cada paso solo después de
que lo confirmes:

| Paso | Cambio | Cómo deshacerlo |
|---|---|---|
| Instrucciones de Claude Code | Añade (o actualiza) una sección breve entre `<!-- claude-toolkit:start -->` y `<!-- claude-toolkit:end -->` al final de `~/.claude/CLAUDE.md`, para que Claude Code sepa cuándo usar cada comando `ctk`. El archivo anterior se copia a `~/.claude/backups/claude-toolkit/`. | `ctk setup --uninstall` |
| Plugin de hooks | Registra este repositorio como el marketplace del plugin `ctk` e instala el plugin `ctk` (`claude plugin marketplace add`, `claude plugin install ctk@ctk`). Consulta [hooks](../../commands/hooks.md). | `ctk setup --uninstall` |
| Dependencias opcionales | Se ofrece a instalar las herramientas que faltan, listadas por `ctk doctor --toolkit` (por ejemplo `gitleaks`, `Xvfb`), con el gestor de paquetes de tu distribución. | tu gestor de paquetes |
| Otros agentes (opcional) | Cuando se encuentra Codex, Gemini CLI u opencode, o con `--agents`: copia las skills de proceso a `~/.agents/skills/` (nunca sobre una skill tuya). `--agents-file ARCHIVO` añade la misma sección breve a un archivo de instrucciones globales que indiques. | `ctk setup --uninstall` (repite `--agents-file ARCHIVO` para el archivo) |

Ejecutar `ctk setup` de nuevo es seguro: solo propone lo que falta o está desactualizado.

## Actualización

```bash
cd /path/to/claude-toolkit
git pull
ctk setup        # refreshes the CLAUDE.md section if it changed
```

Con la instalación editable, `git pull` actualiza `ctk` al instante.

## Desinstalación

```bash
ctk setup --uninstall      # removes the CLAUDE.md section (with a backup) and the plugin
uv tool uninstall claude-toolkit
```

Los logs que escriben `ctk runq` y los hooks están en `~/.cache/claude-toolkit/` y se pueden borrar.

## Sistemas compatibles

Linux (basados en Arch, Debian/Ubuntu, Fedora, openSUSE), macOS y Windows; el
CI prueba los tres. Las sugerencias de instalación se adaptan al gestor de
paquetes detectado; otros sistemas reciben sugerencias genéricas.

### Windows

Instala con `.\install.ps1` en PowerShell (`-Yes`, `-DryRun`; código de salida
`3` cuando necesita aprobación y no hay terminal, igual que `install.sh`). El
plugin necesita [Git for Windows](https://git-scm.com): Claude Code ejecuta los
hooks en Git Bash y, sin él, Claude Code no tiene la herramienta Bash, que las
skills y los agentes del plugin usan para ejecutar `ctk`. Algunos comandos
siguen siendo exclusivos de Linux: `ctk sandbox` (bubblewrap) y
`ctk shoot desktop` (Xvfb).
