# 安装

> 本文翻译自 [installation.md](../../installation.md)，以英文版为准。[README](README.md) · **语言：** [English](../../installation.md) · [Português (Brasil)](../pt-BR/installation.md) · [Español](../es/installation.md) · [Deutsch](../de/installation.md) · **简体中文**

## 快速安装

```bash
git clone https://github.com/nadezhdkov/claude-toolkit.git
cd claude-toolkit
./install.sh
```

`install.sh` 会打印它的计划，并在每一步之前询问：

1. 如果缺少 [uv](https://docs.astral.sh/uv/)，用官方安装程序安装它；
2. 运行 `uv tool install --editable <repo>`，把 `ctk` 放到 `~/.local/bin`；
3. 运行 `ctk setup`。

选项：`--dry-run` 只打印计划；`--yes` 对每个问题都回答“是”（请在读完计划之后再使用）。
没有终端也没有 `--yes` 时，安装程序会在改动任何东西之前以退出码 `3` 停止。

如果 `~/.local/bin` 不在你的 `PATH` 中，请运行 `uv tool update-shell` 并重新启动 shell。

## 手动安装

```bash
uv tool install --editable /path/to/claude-toolkit
ctk setup
```

## `ctk setup` 会修改什么

`ctk setup` 会生成一份计划并打印出来，只有在你确认之后才会执行每一步：

| 步骤 | 改动 | 如何撤销 |
|---|---|---|
| Claude Code 指令 | 在 `~/.claude/CLAUDE.md` 末尾的 `<!-- claude-toolkit:start -->` 和 `<!-- claude-toolkit:end -->` 之间添加（或更新）一小段内容，让 Claude Code 知道何时使用每个 `ctk` 命令。原文件会备份到 `~/.claude/backups/claude-toolkit/`。 | `ctk setup --uninstall` |
| Hooks 插件 | 把本仓库注册为 `ctk` 插件市场，并安装 `ctk` 插件（`claude plugin marketplace add`、`claude plugin install ctk@ctk`）。参见 [hooks](../../commands/hooks.md)。 | `ctk setup --uninstall` |
| 可选依赖 | 主动提出用你所用发行版的包管理器，安装 `ctk doctor --toolkit` 列出的缺失工具（例如 `gitleaks`、`Xvfb`）。 | 你的包管理器 |

再次运行 `ctk setup` 是安全的：它只会提出缺失或已过期的部分。

## 更新

```bash
cd /path/to/claude-toolkit
git pull
ctk setup        # refreshes the CLAUDE.md section if it changed
```

由于是可编辑安装，`git pull` 会立即更新 `ctk`。

## 卸载

```bash
ctk setup --uninstall      # removes the CLAUDE.md section (with a backup) and the plugin
uv tool uninstall claude-toolkit
```

`ctk runq` 和各个 hooks 写入的日志位于 `~/.cache/claude-toolkit/`，可以删除。

## 支持的系统

Linux（基于 Arch、Debian/Ubuntu、Fedora、openSUSE）、macOS 和 Windows；CI 会测试这三者。
安装提示会根据检测到的包管理器给出；其他系统得到通用的提示。

### Windows

在 PowerShell 中用 `.\install.ps1` 安装（支持 `-Yes`、`-DryRun`；需要批准但没有终端时退出码为 `3`，与 `install.sh` 相同）。
插件需要 [Git for Windows](https://git-scm.com)：Claude Code 在 Git Bash 中运行 hooks，
没有它的话，Claude Code 就没有 Bash 工具，而插件的 skills 和代理正是用 Bash 工具来运行 `ctk`。
少数命令仍然只支持 Linux：`ctk sandbox`（bubblewrap）和 `ctk shoot desktop`（Xvfb）。
