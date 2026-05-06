const childProcess = require("child_process");
const fs = require("fs");
const path = require("path");
const vscode = require("vscode");

const DIAGNOSTIC_DELAY_MS = 350;
const DIAGNOSTIC_SOURCE = "logic-language";
const DEFAULT_PYTHON_PATH = process.platform === "win32" ? "py" : "python3";
const CLASS_SYMBOL_COLOR = "#4EC9B0";
const CALLABLE_SYMBOL_COLOR = "#DCDCAA";
const IMPORT_CANDIDATE_LIMIT = 100;

function activate(context) {
  const diagnostics = vscode.languages.createDiagnosticCollection(DIAGNOSTIC_SOURCE);
  const timers = new Map();
  const warningCache = new Set();
  const rootsByUri = new Map();
  const symbolPayloads = new Map();
  const analysisGenerations = new Map();
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
    const env = { ...process.env };
    env.PYTHONIOENCODING = "utf-8";
    return {
      cwd: getBaseDir(document),
      env,
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

  function savedDocumentStateKey(document) {
    return `${document.version}`;
  }

  function cachedSymbolPayload(document) {
    const cached = symbolPayloads.get(document.uri.toString());
    return cached ? cached.payload : undefined;
  }

  function nextAnalysisGeneration(document) {
    const key = document.uri.toString();
    const nextGeneration = (analysisGenerations.get(key) || 0) + 1;
    analysisGenerations.set(key, nextGeneration);
    return nextGeneration;
  }

  function isCurrentAnalysis(document, generation) {
    return !document.isDirty && analysisGenerations.get(document.uri.toString()) === generation;
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

  function normalizeImportPath(text) {
    return text.replace(/\\/g, "/");
  }

  function isQuotedImport(text) {
    return text.startsWith("\"") || text.startsWith("'");
  }

  function stripImportLineComment(text) {
    let quote = "";
    for (let index = 0; index < text.length; index += 1) {
      const char = text[index];
      if (quote) {
        if (char === "\\") {
          index += 1;
          continue;
        }
        if (char === quote) {
          quote = "";
        }
        continue;
      }
      if (char === "#") {
        return text.slice(0, index);
      }
      if (char === "\"" || char === "'") {
        quote = char;
      }
    }
    return text;
  }

  function isRelativeImportPath(importPath) {
    return (
      importPath === "." ||
      importPath === ".." ||
      importPath.startsWith("./") ||
      importPath.startsWith("../")
    );
  }

  function normalizeFsPath(fsPath) {
    const resolved = path.resolve(fsPath);
    return process.platform === "win32" ? resolved.toLowerCase() : resolved;
  }

  function splitImportPrefix(importPath) {
    const normalized = normalizeImportPath(importPath);
    if (!normalized) {
      return { directoryPrefix: "", namePrefix: "" };
    }
    if (normalized.endsWith("/")) {
      return { directoryPrefix: normalized, namePrefix: "" };
    }
    const lastSlash = normalized.lastIndexOf("/");
    if (lastSlash === -1) {
      return { directoryPrefix: "", namePrefix: normalized };
    }
    return {
      directoryPrefix: normalized.slice(0, lastSlash + 1),
      namePrefix: normalized.slice(lastSlash + 1)
    };
  }

  function importRootOptions(document, relativeMode) {
    const roots = [];
    const seen = new Set();

    function addRoot(fsPath, detail, rank) {
      if (!fsPath || !fs.existsSync(fsPath)) {
        return;
      }
      const key = normalizeFsPath(fsPath);
      if (seen.has(key)) {
        return;
      }
      seen.add(key);
      roots.push({ fsPath, detail, rank });
    }

    addRoot(path.dirname(document.fileName), "current directory", 0);
    if (relativeMode) {
      return roots;
    }

    try {
      const { skillRoot } = backendPaths();
      addRoot(skillRoot, "logic-language skill", 1);
      addRoot(path.dirname(skillRoot), "skills directory", 2);
    } catch (_error) {
      // Fall back to current-directory suggestions only when the workspace root is unavailable.
    }
    return roots;
  }

  function importContextForLine(document, lineNumber) {
    if (!isLogicLanguageDocument(document) || document.isUntitled) {
      return undefined;
    }
    const line = document.lineAt(lineNumber);
    const textWithoutComment = stripImportLineComment(line.text);
    const match = textWithoutComment.match(/^(\s*\$import\s+)(.*)$/);
    if (!match) {
      return undefined;
    }

    const prefixLength = match[1].length;
    const rawPath = match[2];

    let quote = "";
    let pathStart = prefixLength;
    let pathEnd = textWithoutComment.length;
    if (isQuotedImport(rawPath)) {
      quote = rawPath[0];
      pathStart += 1;
      const closingQuoteIndex = textWithoutComment.indexOf(quote, pathStart);
      pathEnd = closingQuoteIndex >= 0 ? closingQuoteIndex : textWithoutComment.length;
    } else {
      pathEnd = pathStart;
      while (pathEnd < textWithoutComment.length && !/\s/.test(textWithoutComment[pathEnd])) {
        pathEnd += 1;
      }
    }

    const fullPath = normalizeImportPath(textWithoutComment.slice(pathStart, pathEnd));
    return {
      line,
      quote,
      fullPath,
      pathStart,
      pathEnd
    };
  }

  function importContextAt(document, position) {
    const lineContext = importContextForLine(document, position.line);
    if (!lineContext) {
      return undefined;
    }

    const currentCharacter = Math.min(position.character, lineContext.line.text.length);
    if (currentCharacter < lineContext.pathStart || currentCharacter > lineContext.pathEnd) {
      return undefined;
    }

    const typedPath = normalizeImportPath(
      lineContext.line.text.slice(lineContext.pathStart, currentCharacter)
    );
    return {
      ...lineContext,
      typedPath,
      insertRange: new vscode.Range(position.line, lineContext.pathStart, position.line, lineContext.pathEnd)
    };
  }

  function existingImportFile(fsPath) {
    try {
      return fs.existsSync(fsPath) && fs.statSync(fsPath).isFile() ? path.resolve(fsPath) : undefined;
    } catch (_error) {
      return undefined;
    }
  }

  function resolveImportTarget(document, importPath) {
    const normalizedImportPath = normalizeImportPath(importPath).trim();
    if (!normalizedImportPath) {
      return undefined;
    }

    if (path.isAbsolute(normalizedImportPath)) {
      return existingImportFile(normalizedImportPath);
    }

    const relativeMode = isRelativeImportPath(normalizedImportPath);
    for (const root of importRootOptions(document, relativeMode)) {
      const resolved = existingImportFile(path.resolve(root.fsPath, normalizedImportPath));
      if (resolved) {
        return resolved;
      }
    }
    return undefined;
  }

  function makeImportReplacement(candidatePath, quote) {
    const needsQuotes = /\s/.test(candidatePath);
    const quoteCharToUse = quote || (needsQuotes ? "\"" : "");
    return quoteCharToUse ? `${quoteCharToUse}${candidatePath}${quoteCharToUse}` : candidatePath;
  }

  function collectImportCandidates(document, importPath, options = {}) {
    const normalizedImportPath = normalizeImportPath(importPath);
    const { directoryPrefix, namePrefix } = splitImportPrefix(normalizedImportPath);
    const relativeMode = isRelativeImportPath(normalizedImportPath);
    const roots = importRootOptions(document, relativeMode);
    const includeAllIfNoPrefixMatches = options.includeAllIfNoPrefixMatches === true;

    function collect(prefixFilter) {
      const candidates = new Map();
      const normalizedPrefix = prefixFilter.toLowerCase();

      for (const root of roots) {
        const searchDir = path.resolve(root.fsPath, directoryPrefix || ".");
        if (!fs.existsSync(searchDir) || !fs.statSync(searchDir).isDirectory()) {
          continue;
        }

        let entries;
        try {
          entries = fs.readdirSync(searchDir, { withFileTypes: true });
        } catch (_error) {
          continue;
        }

        for (const entry of entries) {
          const entryName = entry.name;
          const isDirectory = entry.isDirectory();
          if (!isDirectory && path.extname(entryName).toLowerCase() !== ".lp") {
            continue;
          }
          if (normalizedPrefix && !entryName.toLowerCase().startsWith(normalizedPrefix)) {
            continue;
          }

          const resolvedEntryPath = path.resolve(searchDir, entryName);
          const relativeCandidate = normalizeImportPath(path.relative(root.fsPath, resolvedEntryPath));
          const insertPath = isDirectory ? `${relativeCandidate}/` : relativeCandidate;
          const candidateKey = normalizeFsPath(resolvedEntryPath);
          const candidate = {
            insertPath,
            detail: root.detail,
            isDirectory,
            rank: root.rank
          };
          const existing = candidates.get(candidateKey);
          if (
            !existing ||
            insertPath.length < existing.insertPath.length ||
            (insertPath.length === existing.insertPath.length && candidate.rank < existing.rank)
          ) {
            candidates.set(candidateKey, candidate);
          }
        }
      }

      return Array.from(candidates.values())
        .sort((left, right) => {
          if (left.isDirectory !== right.isDirectory) {
            return left.isDirectory ? -1 : 1;
          }
          return left.insertPath.localeCompare(right.insertPath);
        })
        .slice(0, IMPORT_CANDIDATE_LIMIT);
    }

    const exactMatches = collect(namePrefix);
    if (exactMatches.length || !includeAllIfNoPrefixMatches) {
      return exactMatches;
    }
    return collect("");
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
      return;
    }

    const generation = nextAnalysisGeneration(document);
    const stateKey = savedDocumentStateKey(document);

    try {
      const payload = await runModuleCheck(document);
      if (!isCurrentAnalysis(document, generation)) {
        return;
      }
      applyDiagnostics(document.uri, payload);
    } catch (error) {
      if (!isCurrentAnalysis(document, generation)) {
        return;
      }
      diagnostics.delete(document.uri);
      showWarningOnce(
        `Logic Language diagnostics are unavailable: ${error instanceof Error ? error.message : String(error)}`
      );
    }

    try {
      if (!isCurrentAnalysis(document, generation)) {
        return;
      }
      const key = document.uri.toString();
      const cached = symbolPayloads.get(key);
      const payload = cached && cached.stateKey === stateKey ? cached.payload : await runSymbolResolver(document);
      if (!isCurrentAnalysis(document, generation)) {
        return;
      }
      symbolPayloads.set(key, { stateKey, payload });
      applySymbolHighlights(document, payload);
    } catch (error) {
      if (!isCurrentAnalysis(document, generation)) {
        return;
      }
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
    vscode.workspace.onDidSaveTextDocument((document) => scheduleDiagnostics(document)),
    vscode.workspace.onDidCloseTextDocument((document) => {
      diagnostics.delete(document.uri);
      clearSymbolState(document);
      rootsByUri.delete(document.uri.toString());
      analysisGenerations.delete(document.uri.toString());
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
    const cached = cachedSymbolPayload(document);
    if (cached) {
      return cached;
    }
    const stateKey = savedDocumentStateKey(document);
    const payload = await runSymbolResolver(document);
    symbolPayloads.set(key, { stateKey, payload });
    return payload;
  }

  context.subscriptions.push(
    vscode.languages.registerDefinitionProvider("logic-language", {
      async provideDefinition(document, position) {
        if (!isLogicLanguageDocument(document) || document.isUntitled) {
          return undefined;
        }

        const importContext = importContextAt(document, position);
        if (importContext) {
          const importTarget = resolveImportTarget(document, importContext.fullPath);
          if (importTarget) {
            return new vscode.Location(vscode.Uri.file(importTarget), new vscode.Position(0, 0));
          }
          return undefined;
        }

        if (document.isDirty) {
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
    vscode.languages.registerCompletionItemProvider(
      "logic-language",
      {
        provideCompletionItems(document, position) {
          const importContext = importContextAt(document, position);
          if (!importContext) {
            return undefined;
          }

          const candidates = collectImportCandidates(document, importContext.typedPath);
          return candidates.map((candidate) => {
            const item = new vscode.CompletionItem(
              candidate.insertPath,
              candidate.isDirectory ? vscode.CompletionItemKind.Folder : vscode.CompletionItemKind.File
            );
            item.detail = candidate.detail;
            item.range = importContext.insertRange;
            item.insertText = importContext.quote
              ? candidate.insertPath
              : makeImportReplacement(candidate.insertPath, "");
            item.filterText = candidate.insertPath;
            item.sortText = `${candidate.isDirectory ? "0" : "1"}-${candidate.insertPath.toLowerCase()}`;
            return item;
          });
        }
      },
      "/",
      "\"",
      "'",
      "."
    )
  );

  context.subscriptions.push(
    vscode.languages.registerCodeActionsProvider(
      "logic-language",
      {
        provideCodeActions(document, _range, contextForActions) {
          if (!isLogicLanguageDocument(document)) {
            return undefined;
          }

          const actions = [];
          for (const diagnostic of contextForActions.diagnostics) {
            if (String(diagnostic.code || "") !== "missing_import") {
              continue;
            }

            const importContext = importContextForLine(document, diagnostic.range.start.line);
            if (!importContext) {
              continue;
            }

            const candidates = collectImportCandidates(document, importContext.fullPath, {
              includeAllIfNoPrefixMatches: true
            });
            candidates.forEach((candidate, index) => {
              const replacement = makeImportReplacement(candidate.insertPath, importContext.quote);
              const action = new vscode.CodeAction(
                `Replace import with ${replacement}`,
                vscode.CodeActionKind.QuickFix
              );
              action.diagnostics = [diagnostic];
              action.isPreferred = index === 0;
              action.edit = new vscode.WorkspaceEdit();
              action.edit.replace(document.uri, diagnostic.range, replacement);
              actions.push(action);
            });
          }

          return actions;
        }
      },
      {
        providedCodeActionKinds: [vscode.CodeActionKind.QuickFix]
      }
    )
  );

  context.subscriptions.push(
    vscode.window.onDidChangeVisibleTextEditors((editors) => {
      for (const editor of editors) {
        const payload = cachedSymbolPayload(editor.document);
        if (payload) {
          applySymbolHighlights(editor.document, payload);
        }
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
