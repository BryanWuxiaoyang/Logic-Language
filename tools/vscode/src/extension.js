const childProcess = require("child_process");
const path = require("path");
const vscode = require("vscode");

const DIAGNOSTIC_DELAY_MS = 350;
const DIAGNOSTIC_SOURCE = "logic-language";

function activate(context) {
  const diagnostics = vscode.languages.createDiagnosticCollection(DIAGNOSTIC_SOURCE);
  const timers = new Map();
  const warningCache = new Set();
  const rootsByUri = new Map();

  context.subscriptions.push(diagnostics);

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
    return (
      vscode.workspace
        .getConfiguration("logicLanguage", document.uri)
        .get("pythonPath") || "python3"
    );
  }

  function getDocumentLabel(document) {
    if (document.uri.scheme === "file") {
      return document.fileName;
    }
    return document.fileName || document.uri.toString();
  }

  function getBaseDir(document) {
    if (document.uri.scheme === "file") {
      return path.dirname(document.fileName);
    }
    const workspaceFolder = vscode.workspace.workspaceFolders && vscode.workspace.workspaceFolders[0];
    return workspaceFolder ? workspaceFolder.uri.fsPath : context.extensionPath;
  }

  function backendPaths() {
    const scriptsRoot = path.join(context.extensionPath, "python_backend", "scripts");
    const vendorRoot = path.join(context.extensionPath, "python_backend", "vendor");
    const syntaxChecker = path.join(scriptsRoot, "syntax_check.py");
    const semanticChecker = path.join(scriptsRoot, "semantic_check.py");
    return { scriptsRoot, vendorRoot, syntaxChecker, semanticChecker };
  }

  function pythonEnvironment(document) {
    const { scriptsRoot, vendorRoot } = backendPaths();
    const pythonPathEnv = process.env.PYTHONPATH
      ? [scriptsRoot, vendorRoot, process.env.PYTHONPATH].join(path.delimiter)
      : [scriptsRoot, vendorRoot].join(path.delimiter);
    return {
      cwd: getBaseDir(document),
      env: {
        ...process.env,
        PYTHONPATH: pythonPathEnv
      },
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

  function runSyntaxCheck(document) {
    const { syntaxChecker } = backendPaths();
    const args = [
      syntaxChecker,
      "--file",
      document.fileName
    ];

    return runPythonJson(document, args);
  }

  function runSemanticCheck(document, syntaxPayload) {
    const { semanticChecker } = backendPaths();
    const args = [
      semanticChecker,
      "--syntax-json",
      "-",
      document.fileName
    ];
    return runPythonJson(document, args, JSON.stringify(syntaxPayload));
  }

  function toDiagnostic(entry) {
    const line = Math.max(0, Number(entry.lineno) || 0);
    const start = Math.max(0, Number(entry.col_start_no) || 0);
    const end = Math.max(start + 1, Number(entry.col_end_no) || start + 1);
    const severity =
      entry.type === "warning"
        ? vscode.DiagnosticSeverity.Warning
        : vscode.DiagnosticSeverity.Error;
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

  async function runDiagnostics(document) {
    if (!isLogicLanguageDocument(document)) {
      return;
    }
    if (document.isUntitled) {
      diagnostics.delete(document.uri);
      return;
    }

    try {
      const syntaxPayload = await runSyntaxCheck(document);
      const hasSyntaxErrors = Number(syntaxPayload.summary && syntaxPayload.summary.error_count) > 0;
      const payload = hasSyntaxErrors ? syntaxPayload : await runSemanticCheck(document, syntaxPayload);
      applyDiagnostics(document.uri, payload);
    } catch (error) {
      diagnostics.delete(document.uri);
      showWarningOnce(
        `Logic Language diagnostics are unavailable: ${error instanceof Error ? error.message : String(error)}`
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
    vscode.workspace.onDidSaveTextDocument((document) => scheduleDiagnostics(document)),
    vscode.workspace.onDidCloseTextDocument((document) => {
      diagnostics.delete(document.uri);
      rootsByUri.delete(document.uri.toString());
      const key = document.uri.toString();
      const timer = timers.get(key);
      if (timer) {
        clearTimeout(timer);
        timers.delete(key);
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
