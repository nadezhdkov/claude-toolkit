<div align="center">

<img src="../../assets/logo.jpg" alt="logo do claude-toolkit" width="150">

# claude-toolkit

**Ferramentas, hooks, skills e subagentes de uso geral que tornam o Claude Code mais eficaz em qualquer projeto.**

[![CI](https://github.com/nadezhdkov/claude-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/nadezhdkov/claude-toolkit/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/tag/nadezhdkov/claude-toolkit?label=version&color=38bdf8&sort=semver)](../../CHANGELOG.md)
[![License: MIT](https://img.shields.io/github/license/nadezhdkov/claude-toolkit?color=94a3b8)](../../../LICENSE)

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-toolkit-d97757?logo=anthropic&logoColor=white)](https://docs.claude.com/en/docs/claude-code)
[![uv](https://img.shields.io/badge/uv-managed-de5fe9?logo=uv&logoColor=white)](https://docs.astral.sh/uv/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Runtime deps: none](https://img.shields.io/badge/runtime%20deps-none-22c55e)](../../../pyproject.toml)
[![Installer: POSIX sh](https://img.shields.io/badge/installer-POSIX%20sh-4EAA25?logo=gnubash&logoColor=white)](../../../install.sh)

[Por quê](#por-quê) · [Instalação](#instalação) · [Comandos](#comandos) · [Roadmap](../../roadmap.md) · [Design](../../design.md) · [Contribuir](../../../CONTRIBUTING.md)

**Idiomas:** [English](../../../README.md) · **Português (Brasil)** · [Español](../es/README.md) · [Deutsch](../de/README.md) · [简体中文](../zh-CN/README.md)

</div>

---

> Tradução do [README em inglês](../../../README.md), que é a fonte de verdade. As páginas de cada comando, o design, o roadmap e o changelog continuam em inglês.

## Por quê

Agentes de programação com IA perdem tempo e erram nos mesmos lugares em quase
todo projeto. O claude-toolkit ataca quatro deles, cada um medido em sessões
reais do Claude Code:

| Problema | Exemplo | Ferramenta |
|---|---|---|
| Builds e testes falham por causa do ambiente | Node 26 instalado enquanto o repositório fixa a 24; falta `node_modules` | `ctk doctor` |
| Saídas longas de comandos inundam a janela de contexto | Milhares de linhas de teste para achar três falhas | `ctk runq` |
| Navegação no código por grep em vez de definições | Dezenas de leituras de arquivos para achar um padrão | `ctk lsp` |
| Não há como saber se uma mudança ajudou | "Parece mais rápido" | `ctk sessions` |

Todas as ferramentas seguem as mesmas regras: são **rápidas**, **silenciosas
quando está tudo certo** e **nunca alteram seu sistema sem perguntar**. Sem um
terminal (por exemplo, quando o Claude as executa), uma alteração mostra o
plano e sai com o código `3`; uma pessoa aprova e executa de novo com `--yes`.

A saída é **bonita para pessoas e simples para agentes**: cores, gráficos e um
spinner de progresso aparecem apenas em um terminal interativo; pipes, logs e o
Claude Code recebem texto simples e compacto. `NO_COLOR` desliga as cores e
`FORCE_COLOR` as liga.

## Instalação

Requisitos: Linux, macOS ou Windows (com Git Bash), `git` e [uv](https://docs.astral.sh/uv/)
(o instalador se oferece para instalar o uv se ele não existir). O comando `ctk`
não tem dependências de execução além do Python 3.11+.

```bash
git clone https://github.com/nadezhdkov/claude-toolkit.git
cd claude-toolkit
./install.sh            # shows the plan, asks before each step
```

No Windows, no PowerShell: `.\install.ps1` (mesmo plano e mesmas perguntas; `-Yes`, `-DryRun`).

O instalador executa `uv tool install --editable .` (assim `git pull` atualiza
o `ctk`) e depois `ctk setup`, que adiciona uma seção curta a
`~/.claude/CLAUDE.md` dizendo ao Claude Code quando usar cada comando (com
backup) e se oferece para instalar as dependências opcionais que faltarem.
Veja [installation.md](installation.md) para os passos manuais, atualização e
desinstalação.

## Comandos

Execute `ctk` sozinho para ver uma visão geral:

<img src="../../assets/screenshots/overview.svg" alt="tela de visão geral do ctk listando comandos e exemplos">

| Comando | O que faz |
|---|---|
| [`ctk doctor`](../../commands/doctor.md) | Versões fixadas do toolchain × instaladas, e dependências × lockfiles |
| [`ctk runq`](../../commands/runq.md) | Executa um comando; mostra as falhas, o resumo e o caminho do log completo |
| [`ctk lsp`](../../commands/lsp.md) | Servidores de linguagem e plugins LSP do Claude Code de que um projeto precisa |
| [`ctk sessions`](../../commands/sessions.md) | Métricas só de contagem a partir das transcrições do Claude Code |
| [`ctk shoot`](../../commands/shoot.md) | Capturas de tela determinísticas de páginas web, cenas do Godot e aplicativos desktop; baselines e folhas de contato |
| [`ctk audiocheck`](../../commands/audiocheck.md) | Volume, clipping, silêncio e emendas de loop em arquivos de áudio, com imagens de forma de onda e espectrograma |
| [`ctk sandbox`](../../commands/sandbox.md) | Executa código não confiável sem rede, com sistema somente leitura, home vazia e limites de recursos |
| [`ctk libdocs`](../../commands/libdocs.md) | Versão instalada, restrição declarada, README e API de uma dependência; onde um símbolo é definido |
| [`ctk map`](../../commands/map.md) | Mapa compacto dos arquivos e dos símbolos centrais de um repositório; onde um símbolo é usado e quais testes o tocam |
| [`ctk verify`](../../commands/verify.md) | O que está verificado para o código como ele está agora: cada execução do `runq` registrada por estado do código; novo, falhando, desatualizado ou nunca executado |
| [`ctk diffcheck`](../../commands/diffcheck.md) | Verificações determinísticas de uma mudança: API removida ainda em uso, arquivos de risco, restos de depuração, código sem testes |
| [`ctk relay`](../../commands/relay.md) | Passa o trabalho a uma sessão nova do Claude Code em um terminal novo, a partir do arquivo de handoff e do estado verificado |
| [`ctk completion`](../../commands/completion.md) | Autocompletar com Tab para bash, zsh, fish e PowerShell, gerado a partir dos próprios comandos |
| [`ctk setup`](installation.md) | Integra o toolkit ao Claude Code, perguntando antes de cada alteração |
| [`ctk hook`](../../commands/hooks.md) | A lógica por trás dos hooks do plugin (JSON do evento na entrada padrão) |

### `ctk doctor` — verificação do ambiente

Compara o toolchain fixado por um projeto (`.nvmrc`, `.node-version`,
`engines` e `packageManager` do `package.json`, `.python-version`,
`requires-python`, `go.mod`, `rust-toolchain`, `.tool-versions`) com o que está
instalado e verifica se as dependências batem com o lockfile.

<img src="../../assets/screenshots/doctor.svg" alt="saída do ctk doctor: problemas de versão do Node e do lockfile com as correções">

`ctk doctor --toolkit` verifica as dependências do próprio toolkit, com
comandos de instalação para a sua distribuição.

### `ctk runq` — a saída do comando sem o ruído

Executa um comando, salva a saída completa em um log e mostra apenas as falhas,
o resumo e o caminho do log. Saídas curtas são mostradas sem alteração e o
código de saída é sempre preservado. Reconhece pytest, vitest/jest, tsc,
ruff/eslint, cargo, go test e gradle, com um modo genérico para os demais.

<img src="../../assets/screenshots/runq.svg" alt="saída do ctk runq: testes que falharam em destaque com código de saída, tempo e caminho do log">

### `ctk lsp` — servidores de linguagem

Detecta as linguagens do projeto e informa se cada uma tem o binário do
servidor de linguagem e o plugin LSP oficial do Claude Code; `--install` instala
o que falta, perguntando antes de cada item.

<img src="../../assets/screenshots/lsp.svg" alt="saída do ctk lsp: linguagens com o estado do servidor e do plugin e comandos de instalação">

### `ctk sessions` — meça o que ajuda

Lê as transcrições do Claude Code (`~/.claude/projects`) e informa **apenas
contagens**: chamadas de ferramentas e erros, exploração antes da primeira
edição, tamanhos das saídas de comandos, avisos de "arquivo alterado no disco"
e o uso de skills, subagentes, servidores MCP e do `ctk`. `--csv -` imprime
linhas semanais para comparações de antes e depois. O texto das mensagens nunca
é copiado.

<img src="../../assets/screenshots/sessions.svg" alt="saída do ctk sessions: atividade, uso de contexto e um gráfico de barras das ferramentas mais usadas">

### `ctk shoot`: veja o que mudou

Capturas de tela determinísticas, para que o Claude possa olhar a interface que
acabou de alterar: páginas web pelo Chromium do Playwright (animações
congeladas, viewport, fuso horário e idioma fixos), cenas do Godot 4 pelo movie
writer e qualquer programa desktop em um display Xvfb privado. `--baseline`
compara com uma imagem de referência, com limite, tolerância e máscaras, e
grava uma imagem de diferença com a caixa delimitadora da mudança.
`ctk shoot sheet` junta várias capturas em uma folha de contato numerada.

```bash
ctk shoot web localhost:5173 --baseline shots/home.png
ctk shoot godot . --scene res://ui/menu.tscn
```

### `ctk audiocheck`: ouça os problemas sem ouvir

Mede o volume (EBU R128) e o true peak, encontra clipping (mesmo quando foi
atenuado depois), arquivos silenciosos, silêncio nas pontas e DC offset e, com
`--loop`, detecta cliques no ponto de repetição. `--images` grava uma forma de
onda e um espectrograma por arquivo.

```bash
ctk audiocheck assets/audio --target -16 --images
```

### `ctk sandbox`: execute código não confiável com segurança

Executa um comando com bubblewrap: sem rede, com o sistema somente leitura, uma
home vazia (sem chaves SSH nem tokens), só o diretório do projeto gravável, o
ambiente limpo e limites de memória, CPU, processos e tempo.

```bash
ctk sandbox -- npm test
ctk sandbox --dir ~/src/unknown-repo --timeout 300 -- make
```

### `ctk libdocs`: a API que você realmente tem

Lê uma dependência a partir dos arquivos instalados (Python, Node, Rust, Go) e
mostra a versão instalada ao lado da restrição declarada, o README e a API
pública; `--find` mostra a definição de um símbolo com sua assinatura e
documentação. Nada do pacote é importado nem executado.

```bash
ctk libdocs pydantic --find BaseModel.model_dump
```

## Plugin de hooks

O plugin `ctk` do Claude Code adiciona hooks que rodam fora da conversa e não
consomem contexto. Eles ficam em silêncio quando está tudo certo e ignoram os
projetos aos quais não se aplicam:

| Hook | O que faz |
|---|---|
| `format-file` | formata o arquivo que o Claude acabou de editar com o formatador do próprio projeto (ruff, black, prettier, biome, rustfmt, gofmt, stylua, clang-format) |
| `affected-tests` | no fim de um turno, executa os testes relacionados aos arquivos editados; se falharem, o Claude continua trabalhando com o resumo |
| `guard-destructive` | sinaliza `rm -rf` fora do projeto, force-push para `main` e `git reset --hard` sobre trabalho não commitado (só avisa até você mudá-lo para bloquear) |
| `secrets` | executa o `gitleaks` antes do `git commit` e nega commits com segredos |
| `notify` | notificação de desktop quando o Claude Code espera por você ou um turno longo termina |

O `ctk setup` o instala, perguntando antes; manualmente:

```bash
claude plugin marketplace add nadezhdkov/claude-toolkit
claude plugin install ctk@ctk
```

As configurações por projeto e a desativação ficam em `.claude-toolkit.toml`;
veja [docs/commands/hooks.md](../../commands/hooks.md).

## Skills

O plugin também traz skills de processo que o Claude carrega quando uma tarefa
se encaixa, ou que você chama como `/ctk:<nome>`: `debug` (causa raiz antes da
correção), `ship` (verificações, revisão, PR), `handoff` (arquivo de progresso
entre sessões), `onboard-repo`, `visual-qa` (olhar as capturas antes de dar o
trabalho de interface por concluído) e `security-pass`. Elas cedem ao processo
do próprio projeto quando ele existe. Veja [docs/skills.md](../../skills.md).

## Subagentes

`ctk:test-runner`, `ctk:reviewer` e `ctk:researcher` tiram da conversa
principal o trabalho barulhento ou independente e devolvem relatórios curtos
que terminam com um veredito (`pass`/`fail`, `approve`/`changes-requested`,
`answered`/`not-found`), com evidência em `caminho:linha` ou URL. Um hook
impõe esses contratos de saída, e a skill `orchestrate` diz quando delegar e
executa o ciclo implementar → testar → revisar. Veja [docs/agents.md](../../agents.md).

## Benchmark

`benchmark/run.py` executa tarefas fixas com e sem o plugin, cada uma em um
contêiner Docker limpo, e compara pontuação, tokens de contexto, turnos e custo.
Veja [benchmark/README.md](../../../benchmark/README.md).

## Roadmap

A `0.1.0` entregou a base: `doctor`, `runq`, `lsp`, `sessions` e o instalador;
depois vieram o plugin de hooks de qualidade, o `ctk shoot`, o `ctk audiocheck`
e as skills de processo, o `ctk sandbox`, o `ctk libdocs` e subagentes com
contratos de saída impostos. Veja [docs/roadmap.md](../../roadmap.md).

## Desenvolvimento

```bash
uv sync                                               # dev environment
uv run ruff check . && uv run ruff format --check .   # lint and format
uv run pytest                                         # tests
uv run ctk doctor                                     # run the CLI from the checkout
```

Os pull requests executam lint, shellcheck, testes no Python 3.11–3.13, um
teste de fumaça da instalação, a verificação do título em Conventional Commits
e a verificação do changelog; os mantenedores fazem o merge com o label
`automerge`. Veja [CONTRIBUTING.md](../../../CONTRIBUTING.md) e [AGENTS.md](../../../AGENTS.md).

## Licença

[MIT](../../../LICENSE)
