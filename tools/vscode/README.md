# Logic Language for VS Code

Editor support for `.lp`: syntax highlighting, source diagnostics, symbol highlighting and go-to-definition, import and symbol completion, and import Quick Fixes.

## Install a local VSIX

Use VS Code 1.85+, Python 3.11+ with the project's `requirements.txt` installed, and Node.js 20+ with npm for packaging. From the logic-language project root:

```sh
cd tools/vscode
npm ci
npx vsce package --allow-missing-repository --out logic-language.vsix
code --install-extension ./logic-language.vsix
cd ../..
```

Alternatively, open the Extensions view and choose **… → Install from VSIX…**, then select `tools/vscode/logic-language.vsix`. Reload the window if prompted. Node.js is needed to build the VSIX, not to use it.

## Open the backend workspace

The VSIX does not bundle the Python backend. The current extension searches workspace folders for this layout:

```text
workspace/                       ← open this folder
└── skills/
    └── logic-language/
        ├── requirements.txt
        ├── latex-tokens.json
        ├── scripts/
        │   ├── module_check.py
        │   └── resolve_sym_type.py
        └── tools/vscode/
```

Use **File → Open Folder…** to open the parent workspace. In the `Study` repository, open its repository root. For a standalone checkout, place it at `skills/logic-language` within a parent workspace. Opening only the project directory does not satisfy the current lookup.

## Python settings and activation

An empty `logicLanguage.pythonPath` selects `py` on Windows and `python3` elsewhere. To select another interpreter, set **Logic Language: Python Path**, or use this workspace setting with an interpreter command or absolute executable path:

```json
{
  "logicLanguage.pythonPath": "python"
}
```

Install the project's `requirements.txt` using that same interpreter. Open and save `examples/increment.lp`; its language mode should be **Logic Language**. Diagnostics appear in the **Problems** panel. Try **Developer: Reload Window** if the extension does not activate for an already open file.

| Problem | Check |
| --- | --- |
| `logic-language backend not found` | Open the workspace with `skills/logic-language/scripts/`. |
| Python cannot start | Check the interpreter command or absolute path. |
| Python cannot import `lark` | Install `requirements.txt` into the configured environment. |

The extension runs source-tree tools; source diagnostics are not correctness proofs. The extension is licensed under MIT; see `LICENSE.txt`.

<details>
<summary>中文说明 / Read in Chinese</summary>

## 安装本地 VSIX

需要 VS Code 1.85+、安装了项目 `requirements.txt` 的 Python 3.11+，以及用于打包的 Node.js 20+ 和 npm。从 logic-language 项目根目录执行：

```sh
cd tools/vscode
npm ci
npx vsce package --allow-missing-repository --out logic-language.vsix
code --install-extension ./logic-language.vsix
cd ../..
```

也可以在扩展视图选择 **… → 从 VSIX 安装**，选择 `tools/vscode/logic-language.vsix`。如有提示，重新加载窗口。Node.js 用于打包，使用已安装的扩展不需要它。

## 工作区与 Python

VSIX 不包含 Python 后端。当前扩展要求打开的工作区下存在 `skills/logic-language/scripts/module_check.py` 和 `resolve_sym_type.py`。在 `Study` 仓库中打开仓库根目录；独立检出的项目应放在父工作区的 `skills/logic-language` 路径下。仅打开项目目录不满足当前查找规则。

`logicLanguage.pythonPath` 留空时，Windows 默认使用 `py`，其他平台默认使用 `python3`。可以通过 **Logic Language: Python Path** 或以下工作区设置指定解释器命令或绝对路径：

```json
{
  "logicLanguage.pythonPath": "python"
}
```

使用同一个解释器安装项目的 `requirements.txt`。打开并保存 `examples/increment.lp`，语言模式应为 **Logic Language**，诊断显示在 **问题** 面板中。已经打开的文件未启用扩展时，可执行 **开发人员：重新加载窗口**。

出现 `logic-language backend not found` 时检查工作区布局；Python 无法启动时检查解释器路径；无法导入 `lark` 时检查是否将依赖装入正确环境。

扩展提供语法高亮、源文本诊断、符号高亮与跳转、导入与符号补全，以及导入 Quick Fix。诊断不证明程序正确。扩展采用 MIT 许可证，见 `LICENSE.txt`。

</details>
