"use strict";

const assert = require("assert");
const path = require("path");
const { execFileSync } = require("child_process");
const { toDiagnostic } = require("../src/diagnostics");

const vscode = {
  DiagnosticSeverity: { Error: 0, Warning: 1, Information: 2, Hint: 3 },
  Range: class {
    constructor(line, start, endLine, end) {
      this.start = { line, character: start };
      this.end = { line: endLine, character: end };
    }
  },
  Diagnostic: class {
    constructor(range, message, severity) {
      Object.assign(this, { range, message, severity });
    }
  }
};

// Exercise the actual checker payload through the extension's diagnostic adapter.
const source = "{\n    | _x\n    | _x > 0\n    _x < 2\n}";
const checker = path.resolve(__dirname, "../../../scripts/module_check.py");
const payload = JSON.parse(execFileSync(process.env.PYTHON || "python3",
  [checker, "--text", source], { encoding: "utf8" }));
assert.strictEqual(payload.summary.error_count, 0);
const entries = payload.entries.filter(entry => entry.code === "set_stmt_premise");
assert.strictEqual(entries.length, 1);
const diagnostic = toDiagnostic(vscode, entries[0]);
assert.strictEqual(diagnostic.severity, vscode.DiagnosticSeverity.Warning);
assert.strictEqual(diagnostic.source, "logic-language");
assert.strictEqual(diagnostic.code, "set_stmt_premise");
assert.strictEqual(diagnostic.message, entries[0].reason);
assert.deepStrictEqual(diagnostic.range.start, { line: 2, character: 6 });
assert.deepStrictEqual(diagnostic.range.end, { line: 2, character: 12 });

for (const [type, severity] of Object.entries({ error: 0, information: 2, hint: 3 })) {
  assert.strictEqual(toDiagnostic(vscode, { type }).severity, severity);
}
console.log("diagnostics tests passed");
