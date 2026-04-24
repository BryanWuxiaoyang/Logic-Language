const vscode = require("vscode");

const { BackendClient, isLpDocument } = require("./backendClient");
const { ResultDocumentProvider } = require("./resultDocuments");
const { WorkspaceIndex } = require("./workspaceIndex");

const COMMAND_SHOW_CLASS_CURRENT_FILE = "lp.showClassCurrentFile";
const COMMAND_SHOW_CLASS_WORKSPACE = "lp.showClassWorkspace";
const COMMAND_SHOW_INHERITANCE_CURRENT_FILE = "lp.showInheritanceCurrentFile";
const COMMAND_REFRESH_WORKSPACE_INDEX = "lp.refreshWorkspaceIndex";

function activate(context) {
  const backendClient = new BackendClient(context);
  const workspaceIndex = new WorkspaceIndex(backendClient);
  const resultProvider = new ResultDocumentProvider();
  const diagnostics = vscode.languages.createDiagnosticCollection("logic-lp");
  const warningCache = new Set();
  const diagnosticTimers = new Map();

  context.subscriptions.push(
    diagnostics,
    vscode.workspace.registerTextDocumentContentProvider("lp-query", resultProvider)
  );

  function showWarningOnce(message) {
    if (!message || warningCache.has(message)) {
      return;
    }
    warningCache.add(message);
    void vscode.window.showWarningMessage(message);
  }

  function toDiagnostic(item) {
    const line = Math.max(0, (item.line || 1) - 1);
    const character = Math.max(0, (item.column || 1) - 1);
    const range = new vscode.Range(line, character, line, character + 1);
    const severity =
      item.severity === "warning"
        ? vscode.DiagnosticSeverity.Warning
        : vscode.DiagnosticSeverity.Error;
    const diagnostic = new vscode.Diagnostic(range, item.message, severity);
    diagnostic.source = item.source;
    return diagnostic;
  }

  async function runDiagnostics(document) {
    if (!isLpDocument(document)) {
      return;
    }

    try {
      const items = await backendClient.diagnostics(document);
      diagnostics.set(document.uri, items.map(toDiagnostic));
    } catch (error) {
      diagnostics.delete(document.uri);
      showWarningOnce(
        `Logic LP diagnostics are unavailable: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  }

  function scheduleDiagnostics(document, delayMs = 350) {
    if (!isLpDocument(document)) {
      return;
    }

    const key = document.uri.toString();
    const existingTimer = diagnosticTimers.get(key);
    if (existingTimer) {
      clearTimeout(existingTimer);
    }

    const timer = setTimeout(() => {
      diagnosticTimers.delete(key);
      void runDiagnostics(document);
    }, delayMs);
    diagnosticTimers.set(key, timer);
  }

  async function rerunOpenDiagnostics() {
    const openLpDocuments = vscode.workspace.textDocuments.filter(isLpDocument);
    for (const document of openLpDocuments) {
      await runDiagnostics(document);
    }
  }

  async function refreshIndexedFile(filePath) {
    try {
      await workspaceIndex.refreshFile(filePath);
    } catch (error) {
      showWarningOnce(
        `Logic LP workspace index refresh failed for ${filePath}: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  }

  async function openResultDocument(result) {
    const uri = resultProvider.createDocument(result.title, result.content);
    const document = await vscode.workspace.openTextDocument(uri);
    await vscode.window.showTextDocument(document, {
      preview: true,
      preserveFocus: false
    });
  }

  async function requireActiveLpEditor() {
    const editor = vscode.window.activeTextEditor;
    if (!editor || !isLpDocument(editor.document)) {
      await vscode.window.showInformationMessage(
        "Open a .lp file to use Logic LP commands."
      );
      return undefined;
    }
    return editor;
  }

  async function getCurrentFileClasses(filePath) {
    const entry = await workspaceIndex.refreshFile(filePath);
    return entry.classes || [];
  }

  async function showClassCurrentFile() {
    const editor = await requireActiveLpEditor();
    if (!editor) {
      return;
    }

    try {
      const classes = await getCurrentFileClasses(editor.document.fileName);
      if (!classes.length) {
        await vscode.window.showInformationMessage(
          "No classes were found in the current .lp file."
        );
        return;
      }

      const pick = await vscode.window.showQuickPick(
        classes.map((className) => ({ label: className })),
        {
          placeHolder: "Select a class from the current .lp file"
        }
      );
      if (!pick) {
        return;
      }

      const result = await backendClient.queryClass(
        editor.document.fileName,
        pick.label,
        true
      );
      await openResultDocument(result);
    } catch (error) {
      await vscode.window.showErrorMessage(
        `Failed to query the current file: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  }

  async function showClassWorkspace() {
    try {
      if (!workspaceIndex.getWorkspaceClassCandidates().length) {
        await workspaceIndex.rebuild();
      }

      const candidates = workspaceIndex.getWorkspaceClassCandidates();
      if (!candidates.length) {
        await vscode.window.showInformationMessage(
          "No classes were found in the current workspace."
        );
        return;
      }

      const pick = await vscode.window.showQuickPick(
        candidates.map((candidate) => ({
          label: candidate.className,
          description: vscode.workspace.asRelativePath(candidate.filePath, false),
          detail: candidate.filePath,
          candidate
        })),
        {
          placeHolder: "Select a class from the workspace"
        }
      );
      if (!pick) {
        return;
      }

      const result = await backendClient.queryClass(
        pick.candidate.filePath,
        pick.candidate.className,
        true
      );
      await openResultDocument(result);
    } catch (error) {
      await vscode.window.showErrorMessage(
        `Failed to query the workspace: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  }

  async function showInheritanceCurrentFile() {
    const editor = await requireActiveLpEditor();
    if (!editor) {
      return;
    }

    try {
      const classes = await getCurrentFileClasses(editor.document.fileName);
      const picks = [
        {
          label: "All inheritance relations in current file",
          className: undefined
        },
        ...classes.map((className) => ({
          label: className,
          className
        }))
      ];

      const pick = await vscode.window.showQuickPick(picks, {
        placeHolder: "Select a class or inspect all inheritance relations"
      });
      if (!pick) {
        return;
      }

      const result = await backendClient.queryInheritance(
        editor.document.fileName,
        pick.className
      );
      await openResultDocument(result);
    } catch (error) {
      await vscode.window.showErrorMessage(
        `Failed to query inheritance: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  }

  async function refreshWorkspaceIndex() {
    try {
      const count = await workspaceIndex.rebuild();
      await rerunOpenDiagnostics();
      await vscode.window.showInformationMessage(
        `Logic LP workspace index refreshed (${count} files).`
      );
    } catch (error) {
      await vscode.window.showErrorMessage(
        `Failed to refresh the Logic LP workspace index: ${error instanceof Error ? error.message : String(error)}`
      );
    }
  }

  const watcher = vscode.workspace.createFileSystemWatcher("**/*.lp");
  watcher.onDidCreate(async (uri) => {
    await refreshIndexedFile(uri.fsPath);
    await rerunOpenDiagnostics();
  });
  watcher.onDidChange(async (uri) => {
    await refreshIndexedFile(uri.fsPath);
    await rerunOpenDiagnostics();
  });
  watcher.onDidDelete(async (uri) => {
    workspaceIndex.removeFile(uri.fsPath);
    await rerunOpenDiagnostics();
  });

  context.subscriptions.push(
    watcher,
    vscode.workspace.onDidOpenTextDocument((document) => {
      scheduleDiagnostics(document, 25);
    }),
    vscode.workspace.onDidChangeTextDocument((event) => {
      scheduleDiagnostics(event.document);
    }),
    vscode.workspace.onDidSaveTextDocument(async (document) => {
      if (!isLpDocument(document)) {
        return;
      }
      await refreshIndexedFile(document.fileName);
      scheduleDiagnostics(document, 25);
      await rerunOpenDiagnostics();
    }),
    vscode.workspace.onDidCloseTextDocument((document) => {
      if (!isLpDocument(document)) {
        return;
      }
      diagnostics.delete(document.uri);
      const key = document.uri.toString();
      const existingTimer = diagnosticTimers.get(key);
      if (existingTimer) {
        clearTimeout(existingTimer);
        diagnosticTimers.delete(key);
      }
    }),
    vscode.commands.registerCommand(
      COMMAND_SHOW_CLASS_CURRENT_FILE,
      showClassCurrentFile
    ),
    vscode.commands.registerCommand(
      COMMAND_SHOW_CLASS_WORKSPACE,
      showClassWorkspace
    ),
    vscode.commands.registerCommand(
      COMMAND_SHOW_INHERITANCE_CURRENT_FILE,
      showInheritanceCurrentFile
    ),
    vscode.commands.registerCommand(
      COMMAND_REFRESH_WORKSPACE_INDEX,
      refreshWorkspaceIndex
    )
  );

  void workspaceIndex.rebuild().catch((error) => {
    showWarningOnce(
      `Logic LP workspace index is unavailable: ${error instanceof Error ? error.message : String(error)}`
    );
  });

  for (const document of vscode.workspace.textDocuments) {
    scheduleDiagnostics(document, 25);
  }
}

function deactivate() {}

module.exports = {
  activate,
  deactivate
};
