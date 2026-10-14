<div align="center">

<img src="../../assets/logo.jpg" alt="claude-toolkit 标志" width="150">

# claude-toolkit

**通用的工具、hooks、skills 和子代理，让 Claude Code 在任何项目中都更高效。**

[![CI](https://github.com/nadezhdkov/claude-toolkit/actions/workflows/ci.yml/badge.svg)](https://github.com/nadezhdkov/claude-toolkit/actions/workflows/ci.yml)
[![Version](https://img.shields.io/github/v/tag/nadezhdkov/claude-toolkit?label=version&color=38bdf8&sort=semver)](../../CHANGELOG.md)
[![License: MIT](https://img.shields.io/github/license/nadezhdkov/claude-toolkit?color=94a3b8)](../../../LICENSE)

[![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![Claude Code](https://img.shields.io/badge/Claude%20Code-toolkit-d97757?logo=anthropic&logoColor=white)](https://docs.claude.com/en/docs/claude-code)
[![uv](https://img.shields.io/badge/uv-managed-de5fe9?logo=uv&logoColor=white)](https://docs.astral.sh/uv/)
[![Ruff](https://img.shields.io/endpoint?url=https://raw.githubusercontent.com/astral-sh/ruff/main/assets/badge/v2.json)](https://github.com/astral-sh/ruff)
[![Runtime deps: none](https://img.shields.io/badge/runtime%20deps-none-22c55e)](../../../pyproject.toml)
[![Installer: POSIX sh](https://img.shields.io/badge/installer-POSIX%20sh-4EAA25?logo=gnubash&logoColor=white)](../../../install.sh)

[为什么](#为什么) · [安装](#安装) · [命令](#命令) · [路线图](../../roadmap.md) · [设计](../../design.md) · [参与贡献](../../../CONTRIBUTING.md)

**语言：** [English](../../../README.md) · [Português (Brasil)](../pt-BR/README.md) · [Español](../es/README.md) · [Deutsch](../de/README.md) · **简体中文**

</div>

---

> 本文翻译自[英文 README](../../../README.md)，以英文版为准。各命令的页面、设计文档、路线图和更新日志仍为英文。

## 为什么

AI 编程代理在几乎每个项目里都会在相同的地方浪费时间、犯相同的错误。
claude-toolkit 针对其中四类问题，每一类都在真实的 Claude Code 会话中做过度量：

| 问题 | 示例 | 工具 |
|---|---|---|
| 构建和测试因环境原因失败 | 仓库固定使用 Node 24，却装了 Node 26；缺少 `node_modules` | `ctk doctor` |
| 冗长的命令输出塞满上下文窗口 | 为了找出三个失败，要看几千行测试输出 | `ctk runq` |
| 靠 grep 而不是定义来浏览代码 | 为了找一个模式，要读几十个文件 | `ctk lsp` |
| 无法判断某个改动是否有帮助 | “感觉更快了” | `ctk sessions` |

所有工具都遵循同样的规则：**速度快**，**一切正常时保持安静**，并且**绝不在未询问的情况下改动你的系统**。
在没有终端的情况下（例如由 Claude 运行时），需要改动的操作会打印它的计划并以退出码 `3` 结束，
由人批准后再加上 `--yes` 重新运行。

输出**对人友好，对代理简洁**：颜色、图表和进度动画只会出现在交互式终端中；
管道、日志和 Claude Code 得到的是紧凑的纯文本。`NO_COLOR` 关闭颜色，`FORCE_COLOR` 开启颜色。

## 安装

要求：Linux、macOS 或 Windows（需要 Git Bash）、`git` 和 [uv](https://docs.astral.sh/uv/)
（缺少 uv 时，安装程序会主动提出安装）。`ctk` 命令除 Python 3.11+ 之外没有运行时依赖。

```bash
git clone https://github.com/nadezhdkov/claude-toolkit.git
cd claude-toolkit
./install.sh            # shows the plan, asks before each step
```

在 Windows 的 PowerShell 中：`.\install.ps1`（计划和提问都相同；支持 `-Yes`、`-DryRun`）。

安装程序会运行 `uv tool install --editable .`（这样 `git pull` 就能更新 `ctk`），
然后运行 `ctk setup`。后者会在 `~/.claude/CLAUDE.md` 中添加一小段说明，
告诉 Claude Code 何时使用每个命令（会先备份），并主动提出安装缺少的可选依赖。
手动步骤、更新和卸载请参阅 [installation.md](installation.md)。

## 命令

单独运行 `ctk` 可查看概览：

<img src="../../assets/screenshots/overview.svg" alt="ctk 概览界面，列出命令和示例">

| 命令 | 作用 |
|---|---|
| [`ctk doctor`](../../commands/doctor.md) | 对比固定的工具链版本与已安装的版本，以及依赖与 lockfile |
| [`ctk runq`](../../commands/runq.md) | 运行命令；只打印失败项、摘要和完整日志的路径 |
| [`ctk lsp`](../../commands/lsp.md) | 项目所需的语言服务器和 Claude Code LSP 插件 |
| [`ctk sessions`](../../commands/sessions.md) | 基于 Claude Code 会话记录的纯计数指标 |
| [`ctk shoot`](../../commands/shoot.md) | 网页、Godot 场景和桌面应用的确定性截图；基准图和联系表 |
| [`ctk audiocheck`](../../commands/audiocheck.md) | 音频文件的响度、削波、静音和循环接缝检测，并生成波形图和频谱图 |
| [`ctk sandbox`](../../commands/sandbox.md) | 在无网络、系统只读、空白主目录并带资源限制的环境中运行不受信任的代码 |
| [`ctk libdocs`](../../commands/libdocs.md) | 依赖的已安装版本、声明的版本约束、README 和 API；符号的定义位置 |
| [`ctk map`](../../commands/map.md) | 仓库文件和核心符号的紧凑地图；符号在哪里被使用，哪些测试涉及它 |
| [`ctk verify`](../../commands/verify.md) | 当前代码已验证了什么：按代码状态记录每次 `runq` 运行；有效、失败、过期或从未运行 |
| [`ctk diffcheck`](../../commands/diffcheck.md) | 对一次改动的确定性检查：已删除却仍在使用的 API、有风险的文件、调试残留、没有测试的代码 |
| [`ctk relay`](../../commands/relay.md) | 在新终端中把工作交给一个全新的 Claude Code 会话，依据 handoff 文件和已验证的状态 |
| [`ctk setup`](installation.md) | 把工具包接入 Claude Code，每次改动前都会询问 |
| [`ctk hook`](../../commands/hooks.md) | 插件 hooks 背后的逻辑（事件 JSON 从标准输入读取） |

### `ctk doctor` — 环境检查

把项目固定的工具链（`.nvmrc`、`.node-version`、`package.json` 的 `engines` 和 `packageManager`、
`.python-version`、`requires-python`、`go.mod`、`rust-toolchain`、`.tool-versions`）
与实际安装的版本做对比，并检查依赖是否与 lockfile 一致。

<img src="../../assets/screenshots/doctor.svg" alt="ctk doctor 的输出：Node 版本和 lockfile 问题及其修复方法">

`ctk doctor --toolkit` 检查工具包自身的依赖，并给出适用于你的发行版的安装命令。

### `ctk runq` — 没有噪音的命令输出

运行命令，把完整输出保存到日志，只打印失败项、摘要和日志路径。
较短的输出原样打印，退出码始终保留。
能识别 pytest、vitest/jest、tsc、ruff/eslint、cargo、go test 和 gradle，其他情况使用通用的兜底规则。

<img src="../../assets/screenshots/runq.svg" alt="ctk runq 的输出：高亮显示失败的测试，以及退出码、耗时和日志路径">

### `ctk lsp` — 语言服务器

检测项目使用的语言，并报告每种语言是否有语言服务器可执行文件和官方的 Claude Code LSP 插件；
`--install` 会安装缺少的部分，每一项都先询问。

<img src="../../assets/screenshots/lsp.svg" alt="ctk lsp 的输出：各语言的服务器和插件状态以及安装命令">

### `ctk sessions` — 衡量什么真正有帮助

读取 Claude Code 的会话记录（`~/.claude/projects`），**只报告计数**：
工具调用和错误、第一次编辑之前的探索、命令输出的大小、“文件在磁盘上已更改”的提示，
以及 skills、子代理、MCP 服务器和 `ctk` 的使用情况。
`--csv -` 按周输出数据行，便于前后对比。消息文本绝不会被复制。

<img src="../../assets/screenshots/sessions.svg" alt="ctk sessions 的输出：活动、上下文使用情况和最常用工具的条形图">

### `ctk shoot`：看看改了什么

确定性截图，让 Claude 能看到它刚改过的界面：
通过 Playwright 的 Chromium 截取网页（冻结动画，固定视口、时区和语言），
通过 movie writer 截取 Godot 4 场景，
以及在私有的 Xvfb 显示上截取任意桌面程序。
`--baseline` 与参考图像比较，支持阈值、容差和遮罩，并写出带有变化区域边界框的差异图。
`ctk shoot sheet` 把多张截图合并成一张带编号的联系表。

```bash
ctk shoot web localhost:5173 --baseline shots/home.png
ctk shoot godot . --scene res://ui/menu.tscn
```

### `ctk audiocheck`：不用听就能发现问题

测量响度（EBU R128）和真峰值，找出削波（即使事后被衰减过）、静音文件、首尾的静音和直流偏移，
并用 `--loop` 检测循环点处的爆音。`--images` 为每个文件生成一张波形图和一张频谱图。

```bash
ctk audiocheck assets/audio --target -16 --images
```

### `ctk sandbox`：安全地运行不受信任的代码

用 bubblewrap 运行命令：无网络，系统只读，主目录为空（没有 SSH 密钥或令牌），
只有项目目录可写，环境变量被清空，并限制内存、CPU、进程数和时间。

```bash
ctk sandbox -- npm test
ctk sandbox --dir ~/src/unknown-repo --timeout 300 -- make
```

### `ctk libdocs`：你实际拥有的 API

从已安装的文件中读取依赖（Python、Node、Rust、Go），
显示已安装的版本、声明的版本约束、README 和公开 API；
`--find` 会打印某个符号的定义，包括签名和文档。
不会导入或运行包中的任何内容。

```bash
ctk libdocs pydantic --find BaseModel.model_dump
```

## Hooks 插件

Claude Code 的 `ctk` 插件添加了在对话之外运行的 hooks，不占用上下文。
一切正常时它们保持安静，并会跳过不适用的项目：

| Hook | 作用 |
|---|---|
| `format-file` | 用项目自己的格式化工具（ruff、black、prettier、biome、rustfmt、gofmt、stylua、clang-format）格式化 Claude 刚编辑过的文件 |
| `affected-tests` | 在一轮结束时运行与被编辑文件相关的测试；失败时，Claude 带着摘要继续工作 |
| `guard-destructive` | 标出项目之外的 `rm -rf`、对 `main` 的强制推送，以及在有未提交工作时的 `git reset --hard`（在你改为阻止模式之前只发出警告） |
| `secrets` | 在 `git commit` 之前运行 `gitleaks`，拒绝包含密钥的提交 |
| `notify` | 当 Claude Code 在等你，或一轮较长的工作结束时，发送桌面通知 |

`ctk setup` 会安装它（先询问）；手动安装：

```bash
claude plugin marketplace add nadezhdkov/claude-toolkit
claude plugin install ctk@ctk
```

按项目的设置和停用方式写在 `.claude-toolkit.toml` 中；参见 [docs/commands/hooks.md](../../commands/hooks.md)。

## Skills

插件还附带流程类 skills，Claude 会在任务匹配时加载，你也可以用 `/ctk:<名称>` 调用：
`debug`（先找根因再修复）、`ship`（检查、评审、PR）、`handoff`（跨会话的进度文件）、
`onboard-repo`、`visual-qa`（在宣布界面工作完成之前先看截图）和 `security-pass`。
如果项目有自己的流程，它们会让位于项目的流程。参见 [docs/skills.md](../../skills.md)。

## 子代理

`ctk:test-runner`、`ctk:reviewer` 和 `ctk:researcher` 把嘈杂或相互独立的工作从主对话中拿走，
并返回以结论收尾的简短报告（`pass`/`fail`、`approve`/`changes-requested`、`answered`/`not-found`），
附带 `路径:行号` 或 URL 作为证据。一个 hook 负责强制执行这些输出约定，
而 `orchestrate` skill 会说明何时委派，并运行“实现 → 测试 → 评审”的循环。参见 [docs/agents.md](../../agents.md)。

## 基准测试

`benchmark/run.py` 在有插件和没有插件的情况下运行固定任务，每个任务都在干净的 Docker 容器中进行，
并比较得分、上下文 token、轮数和成本。参见 [benchmark/README.md](../../../benchmark/README.md)。

## 路线图

`0.1.0` 交付了基础部分：`doctor`、`runq`、`lsp`、`sessions` 和安装程序；
随后是质量 hooks 插件、`ctk shoot`、`ctk audiocheck` 和流程类 skills、`ctk sandbox`、`ctk libdocs`，
以及带有强制输出约定的子代理。参见 [docs/roadmap.md](../../roadmap.md)。

## 开发

```bash
uv sync                                               # dev environment
uv run ruff check . && uv run ruff format --check .   # lint and format
uv run pytest                                         # tests
uv run ctk doctor                                     # run the CLI from the checkout
```

Pull request 会运行 lint、shellcheck、Python 3.11–3.13 上的测试、安装冒烟测试、
Conventional Commits 标题检查和更新日志检查；维护者通过 `automerge` 标签合并。
参见 [CONTRIBUTING.md](../../../CONTRIBUTING.md) 和 [AGENTS.md](../../../AGENTS.md)。

## 许可证

[MIT](../../../LICENSE)
