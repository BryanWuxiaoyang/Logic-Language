# Logic Language

VS Code diagnostics and import assistance for `.lp` logic-language module text.

## Requirements

- Python 3.11+
- Open the repository workspace root so `skills/logic-language` is available.
- Install the Python dependencies from `skills/logic-language/requirements.txt`.

## Settings

- `logicLanguage.pythonPath`: Python executable used to run the workspace source-tree checker. Defaults to `python3`.

## Features

- Diagnostics for saved `.lp` files
- Symbol highlighting and go-to-definition
- `$import` path autocomplete
- Quick Fix suggestions for missing `$import` targets
