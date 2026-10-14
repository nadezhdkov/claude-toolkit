<div align="center">

<img src="../../assets/logo.jpg" alt="logotipo de claude-toolkit" width="150">

# claude-toolkit

**Herramientas, hooks, skills y subagentes de uso general que hacen que Claude Code sea más eficaz en cualquier proyecto.**

[![CI](https://github.com/nadezhdkov/claude-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/nadezhdkov/claude-toolkit/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/tag/nadezhdkov/claude-toolkit?label=version&color=38bdf8&sort=semver)](../../CHANGELOG.md)
[![License: MIT](https://img.shields.io/github/license/nadezhdkov/claude-toolkit?color=94a3b8)](../../../LICENSE)

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-toolkit-d97757?logo=anthropic&logoColor=white)](https://docs.claude.com/en/docs/claude-code)
[![uv](https://img.shields.io/badge/uv-managed-de5fe9?logo=uv&logoColor=white)](https://docs.astral.sh/uv/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Runtime deps: none](https://img.shields.io/badge/runtime%20deps-none-22c55e)](../../../pyproject.toml)
[![Installer: POSIX sh](https://img.shields.io/badge/installer-POSIX%20sh-4EAA25?logo=gnubash&logoColor=white)](../../../install.sh)

[Por qué](#por-qué) · [Instalación](#instalación) · [Comandos](#comandos) · [Roadmap](../../roadmap.md) · [Diseño](../../design.md) · [Contribuir](../../../CONTRIBUTING.md)

**Idiomas:** [English](../../../README.md) · [Português (Brasil)](../pt-BR/README.md) · **Español** · [Deutsch](../de/README.md) · [简体中文](../zh-CN/README.md)

</div>

---

> Traducción del [README en inglés](../../../README.md), que es la fuente de verdad. Las páginas de cada comando, el diseño, el roadmap y el changelog siguen en inglés.

## Por qué

Los agentes de programación con IA pierden tiempo y se equivocan en los mismos
lugares en casi todos los proyectos. claude-toolkit ataca cuatro de ellos, cada
uno medido en sesiones reales de Claude Code:

| Problema | Ejemplo | Herramienta |
|---|---|---|
| Las compilaciones y las pruebas fallan por el entorno | Node 26 instalado mientras el repositorio fija la 24; falta `node_modules` | `ctk doctor` |
| La salida larga de los comandos inunda la ventana de contexto | Miles de líneas de pruebas para encontrar tres fallos | `ctk runq` |
| Navegación por el código con grep en lugar de definiciones | Decenas de lecturas de archivos para encontrar un patrón | `ctk lsp` |
| No hay forma de saber si un cambio ayudó | «Parece más rápido» | `ctk sessions` |

Todas las herramientas siguen las mismas reglas: son **rápidas**, **silenciosas
cuando todo va bien** y **nunca cambian tu sistema sin preguntar**. Sin
terminal (por ejemplo, cuando Claude las ejecuta), un cambio muestra su plan y
termina con el código `3`; una persona lo aprueba y vuelve a ejecutar con
`--yes`.

La salida está **pensada para personas y es simple para los agentes**: los
colores, los gráficos y un spinner de progreso solo aparecen en un terminal
interactivo; las tuberías, los logs y Claude Code reciben texto simple y
compacto. `NO_COLOR` desactiva el color y `FORCE_COLOR` lo activa.

## Instalación

Requisitos: Linux, macOS o Windows (con Git Bash), `git` y [uv](https://docs.astral.sh/uv/)
(el instalador se ofrece a instalar uv si falta). El comando `ctk` no tiene
dependencias de ejecución más allá de Python 3.11+.

```bash
git clone https://github.com/nadezhdkov/claude-toolkit.git
cd claude-toolkit
./install.sh            # shows the plan, asks before each step
```

En Windows, en PowerShell: `.\install.ps1` (mismo plan y mismas preguntas; `-Yes`, `-DryRun`).

El instalador ejecuta `uv tool install --editable .` (así `git pull` actualiza
`ctk`) y después `ctk setup`, que añade una sección breve a
`~/.claude/CLAUDE.md` para indicar a Claude Code cuándo usar cada comando (con
copia de seguridad) y se ofrece a instalar las dependencias opcionales que
falten. Consulta [installation.md](installation.md) para los pasos manuales, la
actualización y la desinstalación.

## Comandos

Ejecuta `ctk` solo para ver un resumen:

<img src="../../assets/screenshots/overview.svg" alt="pantalla de resumen de ctk con la lista de comandos y ejemplos">

| Comando | Qué hace |
|---|---|
| [`ctk doctor`](../../commands/doctor.md) | Versiones fijadas del toolchain frente a las instaladas, y dependencias frente a los lockfiles |
| [`ctk runq`](../../commands/runq.md) | Ejecuta un comando; muestra los fallos, el resumen y la ruta del log completo |
| [`ctk lsp`](../../commands/lsp.md) | Servidores de lenguaje y plugins LSP de Claude Code que necesita un proyecto |
| [`ctk sessions`](../../commands/sessions.md) | Métricas solo de recuento a partir de las transcripciones de Claude Code |
| [`ctk shoot`](../../commands/shoot.md) | Capturas de pantalla deterministas de páginas web, escenas de Godot y aplicaciones de escritorio; baselines y hojas de contacto |
| [`ctk audiocheck`](../../commands/audiocheck.md) | Volumen, clipping, silencio y empalmes de bucle en archivos de audio, con imágenes de forma de onda y espectrograma |
| [`ctk sandbox`](../../commands/sandbox.md) | Ejecuta código no fiable sin red, con el sistema de solo lectura, un home vacío y límites de recursos |
| [`ctk libdocs`](../../commands/libdocs.md) | Versión instalada, restricción declarada, README y API de una dependencia; dónde se define un símbolo |
| [`ctk map`](../../commands/map.md) | Mapa compacto de los archivos y los símbolos centrales de un repositorio; dónde se usa un símbolo y qué pruebas lo tocan |
| [`ctk verify`](../../commands/verify.md) | Qué está verificado para el código tal como está ahora: cada ejecución de `runq` registrada por estado del código; vigente, fallida, obsoleta o nunca ejecutada |
| [`ctk diffcheck`](../../commands/diffcheck.md) | Comprobaciones deterministas de un cambio: API eliminada que aún se usa, archivos de riesgo, restos de depuración, código sin pruebas |
| [`ctk relay`](../../commands/relay.md) | Pasa el trabajo a una sesión nueva de Claude Code en un terminal nuevo, a partir del archivo de handoff y del estado verificado |
| [`ctk completion`](../../commands/completion.md) | Autocompletado con Tab para bash, zsh, fish y PowerShell, generado a partir de los propios comandos |
| [`ctk setup`](installation.md) | Integra el toolkit en Claude Code, preguntando antes de cada cambio |
| [`ctk hook`](../../commands/hooks.md) | La lógica detrás de los hooks del plugin (JSON del evento por la entrada estándar) |

### `ctk doctor` — comprobación del entorno

Compara el toolchain fijado por un proyecto (`.nvmrc`, `.node-version`,
`engines` y `packageManager` de `package.json`, `.python-version`,
`requires-python`, `go.mod`, `rust-toolchain`, `.tool-versions`) con lo que
está instalado, y comprueba que las dependencias coinciden con el lockfile.

<img src="../../assets/screenshots/doctor.svg" alt="salida de ctk doctor: problemas de versión de Node y del lockfile con sus soluciones">

`ctk doctor --toolkit` comprueba las dependencias del propio toolkit, con
comandos de instalación para tu distribución.

### `ctk runq` — la salida del comando sin ruido

Ejecuta un comando, guarda la salida completa en un log y muestra solo los
fallos, el resumen y la ruta del log. La salida corta se muestra sin cambios y
el código de salida siempre se conserva. Reconoce pytest, vitest/jest, tsc,
ruff/eslint, cargo, go test y gradle, con un modo genérico para el resto.

<img src="../../assets/screenshots/runq.svg" alt="salida de ctk runq: pruebas fallidas resaltadas con código de salida, tiempo y ruta del log">

### `ctk lsp` — servidores de lenguaje

Detecta los lenguajes del proyecto e indica si cada uno tiene el binario de su
servidor de lenguaje y su plugin LSP oficial de Claude Code; `--install`
instala lo que falta, preguntando antes de cada elemento.

<img src="../../assets/screenshots/lsp.svg" alt="salida de ctk lsp: lenguajes con el estado del servidor y del plugin y comandos de instalación">

### `ctk sessions` — mide lo que ayuda

Lee las transcripciones de Claude Code (`~/.claude/projects`) e informa **solo
de recuentos**: llamadas a herramientas y errores, exploración antes de la
primera edición, tamaños de la salida de comandos, avisos de «archivo
modificado en disco» y el uso de skills, subagentes, servidores MCP y `ctk`.
`--csv -` imprime filas semanales para comparar antes y después. El texto de
los mensajes nunca se copia.

<img src="../../assets/screenshots/sessions.svg" alt="salida de ctk sessions: actividad, uso de contexto y un gráfico de barras de las herramientas más usadas">

### `ctk shoot`: mira qué ha cambiado

Capturas de pantalla deterministas, para que Claude pueda ver la interfaz que
acaba de modificar: páginas web con el Chromium de Playwright (animaciones
congeladas, viewport, zona horaria e idioma fijos), escenas de Godot 4 con el
movie writer y cualquier programa de escritorio en un display Xvfb privado.
`--baseline` compara con una imagen de referencia, con umbral, tolerancia y
máscaras, y escribe una imagen de diferencias con el cuadro delimitador del
cambio. `ctk shoot sheet` reúne varias capturas en una hoja de contacto
numerada.

```bash
ctk shoot web localhost:5173 --baseline shots/home.png
ctk shoot godot . --scene res://ui/menu.tscn
```

### `ctk audiocheck`: oye los problemas sin escuchar

Mide el volumen (EBU R128) y el true peak, encuentra clipping (incluso si se
atenuó después), archivos silenciosos, silencio en los extremos y DC offset y,
con `--loop`, detecta clics en el punto de repetición. `--images` escribe una
forma de onda y un espectrograma por archivo.

```bash
ctk audiocheck assets/audio --target -16 --images
```

### `ctk sandbox`: ejecuta código no fiable con seguridad

Ejecuta un comando con bubblewrap: sin red, con el sistema de solo lectura, un
home vacío (sin claves SSH ni tokens), solo el directorio del proyecto con
permiso de escritura, un entorno limpio y límites de memoria, CPU, procesos y
tiempo.

```bash
ctk sandbox -- npm test
ctk sandbox --dir ~/src/unknown-repo --timeout 300 -- make
```

### `ctk libdocs`: la API que realmente tienes

Lee una dependencia a partir de sus archivos instalados (Python, Node, Rust,
Go) y muestra la versión instalada junto a la restricción declarada, el README
y la API pública; `--find` imprime la definición de un símbolo con su firma y
su documentación. No se importa ni se ejecuta nada del paquete.

```bash
ctk libdocs pydantic --find BaseModel.model_dump
```

## Plugin de hooks

El plugin `ctk` de Claude Code añade hooks que se ejecutan fuera de la
conversación y no consumen contexto. Permanecen en silencio cuando todo va bien
y se saltan los proyectos a los que no se aplican:

| Hook | Qué hace |
|---|---|
| `format-file` | formatea el archivo que Claude acaba de editar con el formateador del propio proyecto (ruff, black, prettier, biome, rustfmt, gofmt, stylua, clang-format) |
| `affected-tests` | al final de un turno, ejecuta las pruebas relacionadas con los archivos editados; si fallan, Claude sigue trabajando con el resumen |
| `guard-destructive` | señala `rm -rf` fuera del proyecto, force-push a `main` y `git reset --hard` sobre trabajo sin confirmar (solo avisa hasta que lo cambies a bloquear) |
| `secrets` | ejecuta `gitleaks` antes de `git commit` y rechaza los commits con secretos |
| `notify` | notificación de escritorio cuando Claude Code te espera o termina un turno largo |

`ctk setup` lo instala, preguntando antes; a mano:

```bash
claude plugin marketplace add nadezhdkov/claude-toolkit
claude plugin install ctk@ctk
```

La configuración por proyecto y la desactivación están en `.claude-toolkit.toml`;
consulta [docs/commands/hooks.md](../../commands/hooks.md).

## Skills

El plugin también incluye skills de proceso que Claude carga cuando una tarea
encaja, o que invocas como `/ctk:<nombre>`: `debug` (causa raíz antes de la
corrección), `ship` (comprobaciones, revisión, PR), `handoff` (archivo de
progreso entre sesiones), `onboard-repo`, `visual-qa` (mirar las capturas antes
de dar por terminado el trabajo de interfaz) y `security-pass`. Ceden ante el
proceso propio del proyecto cuando existe. Consulta [docs/skills.md](../../skills.md).

## Subagentes

`ctk:test-runner`, `ctk:reviewer` y `ctk:researcher` sacan de la conversación
principal el trabajo ruidoso o independiente y devuelven informes breves que
terminan con un veredicto (`pass`/`fail`, `approve`/`changes-requested`,
`answered`/`not-found`), con evidencia en `ruta:línea` o URL. Un hook hace
cumplir estos contratos de salida, y la skill `orchestrate` indica cuándo
delegar y ejecuta el ciclo implementar → probar → revisar. Consulta
[docs/agents.md](../../agents.md).

## Benchmark

`benchmark/run.py` ejecuta tareas fijas con y sin el plugin, cada una en un
contenedor Docker limpio, y compara puntuación, tokens de contexto, turnos y
coste. Consulta [benchmark/README.md](../../../benchmark/README.md).

## Roadmap

La `0.1.0` entregó la base: `doctor`, `runq`, `lsp`, `sessions` y el
instalador; después llegaron el plugin de hooks de calidad, `ctk shoot`,
`ctk audiocheck` y las skills de proceso, `ctk sandbox`, `ctk libdocs` y los
subagentes con contratos de salida obligatorios. Consulta
[docs/roadmap.md](../../roadmap.md).

## Desarrollo

```bash
uv sync                                               # dev environment
uv run ruff check . && uv run ruff format --check .   # lint and format
uv run pytest                                         # tests
uv run ctk doctor                                     # run the CLI from the checkout
```

Los pull requests ejecutan lint, shellcheck, pruebas en Python 3.11–3.13, una
prueba de humo de la instalación, la comprobación del título en Conventional
Commits y la comprobación del changelog; los mantenedores hacen el merge con la
etiqueta `automerge`. Consulta [CONTRIBUTING.md](../../../CONTRIBUTING.md) y
[AGENTS.md](../../../AGENTS.md).

## Licencia

[MIT](../../../LICENSE)
