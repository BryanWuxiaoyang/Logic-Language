# Logic LP Tools

Local VSCode extension for `.lp` logic programs.

## Features

- Syntax highlighting for `.lp`
- Diagnostics powered by the shared `logic-language` Python parser
- Command palette queries for class details and inheritance graphs
- Workspace index over `**/*.lp`

## Requirements

- Python 3.11+
- A workspace containing `skills/logic-language/scripts`

## Settings

- `lp.pythonPath`
- `lp.backendScriptsRoot`

## Commands

- `LP: Show Class (Current File)`
- `LP: Show Class (Workspace)`
- `LP: Show Inheritance (Current File)`
- `LP: Refresh Workspace Index`
