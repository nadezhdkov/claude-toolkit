# Instalação

> Tradução de [installation.md](../../installation.md), que é a fonte de verdade. [README](README.md) · **Idiomas:** [English](../../installation.md) · **Português (Brasil)** · [Español](../es/installation.md) · [Deutsch](../de/installation.md) · [简体中文](../zh-CN/installation.md)

## Instalação rápida

```bash
git clone https://github.com/nadezhdkov/claude-toolkit.git
cd claude-toolkit
./install.sh
```

O `install.sh` mostra seu plano e pergunta antes de cada passo:

1. instala o [uv](https://docs.astral.sh/uv/) com o instalador oficial, se ele não existir;
2. executa `uv tool install --editable <repo>`, que coloca o `ctk` em `~/.local/bin`;
3. executa `ctk setup`.

Opções: `--dry-run` só mostra o plano; `--yes` responde sim a todas as
perguntas (use só depois de ler o plano). Sem um terminal e sem `--yes`, o
instalador para com o código de saída `3` antes de alterar qualquer coisa.

Se `~/.local/bin` não estiver no seu `PATH`, execute `uv tool update-shell` e
reinicie o shell.

## Instalação manual

```bash
uv tool install --editable /path/to/claude-toolkit
ctk setup
```

## O que o `ctk setup` altera

O `ctk setup` monta um plano, mostra-o e só aplica cada passo depois que você o
confirma:

| Passo | Alteração | Como desfazer |
|---|---|---|
| Instruções do Claude Code | Adiciona (ou atualiza) uma seção curta entre `<!-- claude-toolkit:start -->` e `<!-- claude-toolkit:end -->` no fim de `~/.claude/CLAUDE.md`, para que o Claude Code saiba quando usar cada comando `ctk`. O arquivo anterior é copiado para `~/.claude/backups/claude-toolkit/`. | `ctk setup --uninstall` |
| Plugin de hooks | Registra este repositório como o marketplace do plugin `ctk` e instala o plugin `ctk` (`claude plugin marketplace add`, `claude plugin install ctk@ctk`). Veja [hooks](../../commands/hooks.md). | `ctk setup --uninstall` |
| Dependências opcionais | Oferece instalar as ferramentas que faltam, listadas por `ctk doctor --toolkit` (por exemplo `gitleaks`, `Xvfb`), com o gerenciador de pacotes da sua distribuição. | seu gerenciador de pacotes |

Executar o `ctk setup` de novo é seguro: ele só propõe o que falta ou está desatualizado.

## Atualização

```bash
cd /path/to/claude-toolkit
git pull
ctk setup        # refreshes the CLAUDE.md section if it changed
```

Com a instalação editável, o `git pull` atualiza o `ctk` imediatamente.

## Desinstalação

```bash
ctk setup --uninstall      # removes the CLAUDE.md section (with a backup) and the plugin
uv tool uninstall claude-toolkit
```

Os logs gravados pelo `ctk runq` e pelos hooks ficam em `~/.cache/claude-toolkit/` e podem ser apagados.

## Sistemas suportados

Linux (baseados em Arch, Debian/Ubuntu, Fedora, openSUSE), macOS e Windows; o
CI testa os três. As dicas de instalação se adaptam ao gerenciador de pacotes
detectado; outros sistemas recebem dicas genéricas.

### Windows

Instale com `.\install.ps1` no PowerShell (`-Yes`, `-DryRun`; código de saída
`3` quando precisa de aprovação e não há terminal, como no `install.sh`). O
plugin precisa do [Git for Windows](https://git-scm.com): o Claude Code executa
os hooks no Git Bash e, sem ele, o Claude Code não tem a ferramenta Bash, que
as skills e os agentes do plugin usam para executar o `ctk`. Alguns comandos
continuam exclusivos do Linux: `ctk sandbox` (bubblewrap) e `ctk shoot desktop`
(Xvfb).
