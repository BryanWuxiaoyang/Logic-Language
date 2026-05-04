const childProcess = require("child_process");
const fs = require("fs");
const path = require("path");
const vscode = require("vscode");

const DIAGNOSTIC_DELAY_MS = 350;
const DIAGNOSTIC_SOURCE = "logic-language";
const DEFAULT_PYTHON_PATH = process.platform === "win32" ? "py" : "python3";
const CLASS_SYMBOL_COLOR = "#4EC9B0";
const CALLABLE_SYMBOL_COLOR = "#DCDCAA";

function activate(context) {
  const diagnostics = vscode.languages.createDiagnosticCollection(DIAGNOSTIC_SOURCE);
  const timers = new Map();
  const warningCache = new Set();
  const rootsByUri = new Map();
  const symbolPayloads = new Map();
  const classSymbolDecoration = vscode.window.createTextEditorDecorationType({
    color: CLASS_SYMBOL_COLOR
  });
  const callableSymbolDecoration = vscode.window.createTextEditorDecorationType({
    color: CALLABLE_SYMBOL_COLOR
  });

  context.subscriptions.push(diagnostics, classSymbolDecoration, callableSymbolDecoration);

  function showWarningOnce(message) {
    if (!message || warningCache.has(message)) {
      return;
    }
    warningCache.add(message);
    void vscode.window.showWarningMessage(message);
  }

  function isLogicLanguageDocument(document) {
    return (
      document &&
      document.uri &&
      document.uri.scheme === "file" &&
      document.languageId === "logic-language"
    );
  }

  function getPythonPath(document) {
    const configuredPath = vscode.workspace
      .getConfiguration("logicLanguage", document.uri)
      .get("pythonPath");
    if (typeof configuredPath === "string" && configuredPath.trim()) {
      return configuredPath.trim();
    }
    return DEFAULT_PYTHON_PATH;
  }

  function getBaseDir(document) {
    if (document.uri.scheme === "file") {
      return path.dirname(document.fileName);
    }
    const workspaceFolder = vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0];
    return workspaceFolder ? workspaceFolder.uri.fsPath : context.extensionPath;
  }

  function resolveWorkspaceRoot() {
    const workspaceFolders = vscode.workspace.workspaceFolders || [];
    for (const folder of workspaceFolders) {
      const root = folder.uri.fsPath;
      const skillRoot = path.join(root, "skills", "logic-language");
      const scriptsRoot = path.join(skillRoot, "scripts");
      const moduleChecker = path.join(scriptsRoot, "module_check.py");
      const symResolver = path.join(scriptsRoot, "resolve_sym_type.py");
      if (fs.existsSync(moduleChecker) && fs.existsSync(symResolver)) {
        return { root, skillRoot, scriptsRoot, moduleChecker, symResolver };
      }
    }
    throw new Error(
      "logic-language backend not found. Open the repository workspace root containing skills/logic-language."
    );
  }

  function backendPaths() {
    return resolveWorkspaceRoot();
  }

  function pythonEnvironment(document) {
    return {
      cwd: getBaseDir(document),
      env: { ...process.env },
      windowsHide: true
    };
  }

  function runPythonJson(document, args, stdinText) {
    const pythonPath = getPythonPath(document);
    return new Promise((resolve, reject) => {
      const child = childProcess.spawn(pythonPath, args, pythonEnvironment(document));

      let stdout = "";
      let stderr = "";

      child.stdout.on("data", (chunk) => {
        stdout += chunk.toString("utf8");
      });
      child.stderr.on("data", (chunk) => {
        stderr += chunk.toString("utf8");
      });
      child.on("error", reject);
      child.on("close", (code) => {
        if (code !== 0 && code !== 1) {
          const detail = stderr.trim() || stdout.trim() || `checker exited with code ${code}`;
          reject(new Error(detail));
          return;
        }

        try {
          resolve(JSON.parse(stdout));
        } catch (error) {
          reject(
            new Error(
              `failed to parse checker JSON: ${error instanceof Error ? error.message : String(error)}`
            )
          );
        }
      });

      if (stdinText !== undefined) {
        child.stdin.write(stdinText);
      }
      child.stdin.end();
    });
  }

  function runModuleCheck(document) {
    const { moduleChecker } = backendPaths();
    const args = [
      moduleChecker,
      "--file",
      document.fileName
    ];

    return runPythonJson(document, args);
  }

  function runSymbolResolver(document) {
    const { symResolver } = backendPaths();
    const args = [
      symResolver,
      "--file",
      document.fileName
    ];

    return runPythonJson(document, args);
  }

  function toDiagnostic(entry) {
    const line = Math.max(0, Number(entry.lineno) || 0);
    const start = Math.max(0, Number(entry.col_start_no) || 0);
    const end = Math.max(start + 1, Number(entry.col_end_no) || start + 1);
    let severity = vscode.DiagnosticSeverity.Error;
    if (entry.type === "warning") {
      severity = vscode.DiagnosticSeverity.Warning;
    } else if (entry.type === "information") {
      severity = vscode.DiagnosticSeverity.Information;
    } else if (entry.type === "hint") {
      severity = vscode.DiagnosticSeverity.Hint;
    }
    const diagnostic = new vscode.Diagnostic(
      new vscode.Range(line, start, line, end),
      entry.reason || entry.code || "logic-language syntax issue",
      severity
    );
    diagnostic.source = DIAGNOSTIC_SOURCE;
    if (entry.code) {
      diagnostic.code = entry.code;
    }
    return diagnostic;
  }

  function uriForFile(file) {
    if (!file || file === "<stdin>" || file === "__stdin__") {
      return undefined;
    }
    return vscode.Uri.file(file);
  }

  function applyDiagnostics(rootUri, payload) {
    const previous = rootsByUri.get(rootUri.toString()) || new Set();
    const next = new Set();
    const grouped = new Map();

    for (const entry of payload.entries || []) {
      const uri = uriForFile(entry.file);
      if (!uri) {
        continue;
      }
      const key = uri.toString();
      next.add(key);
      if (!grouped.has(key)) {
        grouped.set(key, { uri, entries: [] });
      }
      grouped.get(key).entries.push(entry);
    }

    for (const key of previous) {
      if (!next.has(key)) {
        diagnostics.delete(vscode.Uri.parse(key));
      }
    }

    for (const { uri, entries } of grouped.values()) {
      diagnostics.set(uri, entries.map(toDiagnostic));
    }

    if (!grouped.has(rootUri.toString())) {
      diagnostics.set(rootUri, []);
    }
    rootsByUri.set(rootUri.toString(), next);
  }

  function rangesFor(entries, type) {
    return entries
      .filter((entry) => entry.colorable && entry.type === type)
      .map((entry) => {
        const line = Math.max(0, Number(entry.lineno) || 0);
        const start = Math.max(0, Number(entry.col_start_no) || 0);
        const end = Math.max(start + 1, Number(entry.col_end_no) || start + 1);
        return new vscode.Range(line, start, line, end);
      });
  }

  function visibleEditorsForDocument(document) {
    return vscode.window.visibleTextEditors.filter(
      (editor) => editor.document.uri.toString() === document.uri.toString()
    );
  }

  function clearSymbolHighlights(document) {
    for (const editor of visibleEditorsForDocument(document)) {
      editor.setDecorations(classSymbolDecoration, []);
      editor.setDecorations(callableSymbolDecoration, []);
    }
  }

  function clearSymbolState(document) {
    symbolPayloads.delete(document.uri.toString());
    clearSymbolHighlights(document);
  }

  function applySymbolHighlights(document, payload) {
    const entries = Array.isArray(payload.occurrences) ? payload.occurrences : [];
    const classRanges = rangesFor(entries, "class");
    const callableRanges = [
      ...rangesFor(entries, "func"),
      ...rangesFor(entries, "pred")
    ];
    for (const editor of visibleEditorsForDocument(document)) {
      editor.setDecorations(classSymbolDecoration, classRanges);
      editor.setDecorations(callableSymbolDecoration, callableRanges);
    }
  }

  async function runDiagnostics(document) {
    if (!isLogicLanguageDocument(document)) {
      return;
    }
    if (document.isUntitled) {
      diagnostics.delete(document.uri);
      clearSymbolState(document);
      return;
    }
    if (document.isDirty) {
      clearSymbolState(document);
      return;
    }

    try {
      const payload = await runModuleCheck(document);
      applyDiagnostics(document.uri, payload);
    } catch (error) {
      diagnostics.delete(document.uri);
      showWarningOnce(
        `Logic Language diagnostics are unavailable: ${error instanceof Error ? error.message : String(error)}`
      );
    }

    try {
      const payload = await runSymbolResolver(document);
      symbolPayloads.set(document.uri.toString(), payload);
      applySymbolHighlights(document, payload);
    } catch (error) {
      clearSymbolState(document);
      showWarningOnce(
        `Logic Language symbol highlighting is unavailable: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  }

  function scheduleDiagnostics(document) {
    if (!isLogicLanguageDocument(document)) {
      return;
    }

    const key = document.uri.toString();
    const existingTimer = timers.get(key);
    if (existingTimer) {
      clearTimeout(existingTimer);
    }

    const timer = setTimeout(() => {
      timers.delete(key);
      void runDiagnostics(document);
    }, DIAGNOSTIC_DELAY_MS);
    timers.set(key, timer);
  }

  context.subscriptions.push(
    vscode.workspace.onDidOpenTextDocument((document) => scheduleDiagnostics(document)),
    vscode.workspace.onDidChangeTextDocument((event) => {
      if (isLogicLanguageDocument(event.document)) {
        clearSymbolState(event.document);
      }
    }),
    vscode.workspace.onDidSaveTextDocument((document) => scheduleDiagnostics(document)),
    vscode.workspace.onDidCloseTextDocument((document) => {
      diagnostics.delete(document.uri);
      clearSymbolState(document);
      rootsByUri.delete(document.uri.toString());
      const key = document.uri.toString();
      const timer = timers.get(key);
      if (timer) {
        clearTimeout(timer);
        timers.delete(key);
      }
    })
  );

  function rangeFromEntry(entry) {
    const line = Math.max(0, Number(entry.lineno) || 0);
    const start = Math.max(0, Number(entry.col_start_no) || 0);
    const end = Math.max(start + 1, Number(entry.col_end_no) || start + 1);
    return new vscode.Range(line, start, line, end);
  }

  function containsPosition(entry, position) {
    const line = Math.max(0, Number(entry.lineno) || 0);
    const start = Math.max(0, Number(entry.col_start_no) || 0);
    const end = Math.max(start + 1, Number(entry.col_end_no) || start + 1);
    return line === position.line && position.character >= start && position.character < end;
  }

  function findOccurrenceAt(payload, position) {
    const entries = Array.isArray(payload && payload.occurrences) ? payload.occurrences : [];
    return entries.find((entry) => containsPosition(entry, position));
  }

  async function resolveSymbolPayload(document) {
    const key = document.uri.toString();
    const cached = symbolPayloads.get(key);
    if (cached) {
      return cached;
    }
    const payload = await runSymbolResolver(document);
    symbolPayloads.set(key, payload);
    return payload;
  }

  context.subscriptions.push(
    vscode.languages.registerDefinitionProvider("logic-language", {
      async provideDefinition(document, position) {
        if (!isLogicLanguageDocument(document) || document.isUntitled || document.isDirty) {
          return undefined;
        }
        try {
          const payload = await resolveSymbolPayload(document);
          const occurrence = findOccurrenceAt(payload, position);
          if (!occurrence || !occurrence.definition) {
            return undefined;
          }
          const uri = uriForFile(occurrence.definition.file);
          if (!uri) {
            return undefined;
          }
          return new vscode.Location(uri, rangeFromEntry(occurrence.definition));
        } catch (error) {
          showWarningOnce(
            `Logic Language go to definition is unavailable: ${error instanceof Error ? error.message : String(error)}`
          );
          return undefined;
        }
      }
    })
  );

  context.subscriptions.push(
    vscode.window.onDidChangeVisibleTextEditors((editors) => {
      for (const editor of editors) {
        scheduleDiagnostics(editor.document);
      }
    })
  );

  for (const document of vscode.workspace.textDocuments) {
    scheduleDiagnostics(document);
  }
}

function deactivate() {}

module.exports = {
  activate,
  deactivate
};
