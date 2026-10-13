# `ctk lsp`

Claude Code gets go-to-definition, references and type information from LSP
plugins in the official marketplace (`claude-plugins-official`). Each plugin
needs its language server binary on `PATH`. `ctk lsp` shows what a project
needs and what is missing.

```bash
ctk lsp [path]             # report (exit 1 if something is missing)
ctk lsp --install [path]   # install missing servers and plugins, asking before each
ctk lsp --install --yes    # no questions (only after reading the report)
```

## How languages are detected

Files come from `git ls-files` (tracked and untracked, respecting
`.gitignore`), or a bounded directory walk that skips `node_modules`, `.venv`,
`dist`, `build`, `target` and similar. A language needs at least 3 files to be
reported.

## Supported languages

| Language | Plugin | Server binary | Install (examples) |
|---|---|---|---|
| Python | `pyright-lsp` | `pyright-langserver` | `npm install -g pyright` or `uv tool install pyright` |
| TypeScript / JavaScript | `typescript-lsp` | `typescript-language-server` | `npm install -g typescript-language-server typescript` |
| Go | `gopls-lsp` | `gopls` | `go install golang.org/x/tools/gopls@latest` |
| Rust | `rust-analyzer-lsp` | `rust-analyzer` | `pacman -S rust-analyzer`, `rustup component add rust-analyzer` |
| C / C++ | `clangd-lsp` | `clangd` | `pacman -S clang`, `apt install clangd` |
| Java | `jdtls-lsp` | `jdtls` | AUR `jdtls`, `brew install jdtls` |
| Kotlin | `kotlin-lsp` | `kotlin-lsp` | `brew install JetBrains/utils/kotlin-lsp` |
| C# | `csharp-lsp` | `csharp-ls` | `dotnet tool install --global csharp-ls` |
| Lua | `lua-lsp` | `lua-language-server` | `pacman -S lua-language-server` |
| PHP | `php-lsp` | `intelephense` | `npm install -g intelephense` |
| Ruby | `ruby-lsp` | `ruby-lsp` | `gem install ruby-lsp` |
| Swift | `swift-lsp` | `sourcekit-lsp` | Swift toolchain |

Plugins are installed with `claude plugin install <plugin>@claude-plugins-official`.
A plugin counts as available when it is installed and not disabled in
`~/.claude/settings.json`. Commands that need `sudo` must be run by a person in
a terminal.

## Done criteria

- For each language with a plugin, a definition and a references lookup work in a real project.
- `ctk doctor --toolkit` and `ctk lsp` report missing servers instead of failing later.
