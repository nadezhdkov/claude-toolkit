# `ctk completion`

Prints the tab completion script of a shell. The scripts are generated from the command line
parser, so a new command or option is completed the moment it exists, with nothing to keep in sync.

```bash
# bash: ~/.bashrc
eval "$(ctk completion bash)"

# zsh: ~/.zshrc, after compinit
source <(ctk completion zsh)

# fish: ~/.config/fish/config.fish
ctk completion fish | source

# PowerShell: $PROFILE
ctk completion powershell | Out-String | Invoke-Expression
```

Nothing is installed or written: the command only prints, so you decide where it goes.

## What is completed

- the commands and the kinds of `ctk shoot` (`web`, `godot`, `desktop`, `compare`, `sheet`);
- the options of each command, with their description in fish, zsh and PowerShell;
- the fixed values of an argument: `ctk verify` (`status`, `run`), `ctk hook <name>`,
  `ctk libdocs --ecosystem`, `ctk completion <shell>`.

Everything else (a path, a package name, a URL) is left to the shell's own completion, which
offers files. Options hidden from `--help` (such as `--root`) are not offered.

```text
$ ctk sh<Tab>            →  shoot
$ ctk shoot <Tab>        →  web  godot  desktop  compare  sheet
$ ctk doctor --<Tab>     →  --toolkit  --json  --verbose  --help
```

## Done criteria (tested in `tests/test_completion.py`)

- Every command, nested kind and option of the parser is in the script of every shell, and
  suppressed options are in none.
- bash, fish and PowerShell are run for real and offer the right words for commands, nested
  commands, options and choices, and nothing for a path. zsh is loaded through `compinit`, and
  every script passes its shell's syntax check (PowerShell's parser).
- An unknown shell exits `2`.
