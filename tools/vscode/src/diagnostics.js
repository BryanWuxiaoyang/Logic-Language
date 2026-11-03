"use strict";

function toDiagnostic(vscode, entry, source = "logic-language") {
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
  diagnostic.source = source;
  if (entry.code) {
    diagnostic.code = entry.code;
  }
  return diagnostic;
}

module.exports = { toDiagnostic };
