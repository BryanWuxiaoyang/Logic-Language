"use strict";

const assert = require("assert");
const {
  classMethodFirstParamCompletionContext,
  completionFilterText,
  completionRankForSymbol,
  parseBinderNames,
  parseSignatureTerms
} = require("../src/completion_helpers");

function context(line, activeClassName) {
  return classMethodFirstParamCompletionContext(line, line.length, activeClassName);
}

function applyCompletion(line, completion) {
  return line.slice(0, completion.replaceStart) + completion.insertText + line.slice(completion.replaceEnd);
}

{
  const completion = context("Value::func:");
  assert(completion);
  assert.strictEqual(completion.label, "(_value");
  assert.strictEqual(applyCompletion("Value::func:", completion), "Value::func: (_value");
}

{
  const completion = context("    ::func:", "Value");
  assert(completion);
  assert.strictEqual(completion.label, "(_value");
  assert.strictEqual(applyCompletion("    ::func:", completion), "    ::func: (_value");
}

{
  const line = "    ::func: ";
  const completion = context(line, "Value");
  assert(completion);
  assert.strictEqual(completion.label, "(_value");
  assert.strictEqual(applyCompletion(line, completion), "    ::func: (_value");
}

{
  const line = "    ::func: (_v";
  const completion = context(line, "Value");
  assert(completion);
  assert.strictEqual(completion.label, "(_value");
  assert.strictEqual(applyCompletion(line, completion), "    ::func: (_value");
}

assert.strictEqual(context("    ::func: (_value,", "Value"), undefined);
assert.strictEqual(context("func:"), undefined);

assert.deepStrictEqual(parseSignatureTerms("(_shader_env, _unit_group)"), ["_shader_env", "_unit_group"]);
assert.deepStrictEqual(parseSignatureTerms("_shader_env"), ["_shader_env"]);
assert.deepStrictEqual(parseSignatureTerms("(_shader_env, _unit_group) => _unused"), []);
assert.deepStrictEqual(parseBinderNames("| _raw_coord = _ldibk_instr.raw_coord(_gpu_mem, _thread)"), ["_raw_coord"]);
assert.deepStrictEqual(parseBinderNames("| _id1, _id2"), ["_id1", "_id2"]);
assert.deepStrictEqual(parseBinderNames("| _wave ∈ _waves"), ["_wave"]);
assert.deepStrictEqual(parseBinderNames("| _wave \\in _waves"), ["_wave"]);
assert.deepStrictEqual(parseBinderNames("| _instr => _stream_processor.waiting_waves(_instr)"), ["_instr"]);
assert.deepStrictEqual(parseBinderNames("| _id1 < _id2"), []);

assert.strictEqual(completionFilterText("_unit_group", "unit_group"), "unit_group");
assert.strictEqual(completionFilterText("_unit_group", "_unit_group"), "_unit_group");

assert(
  completionRankForSymbol("pure", "current_bound", "unit_group") <
    completionRankForSymbol("func", "global", "unit_group")
);
assert(
  completionRankForSymbol("pure", "ancestor_bound", "unit_group") <
    completionRankForSymbol("class", "global", "unit_group")
);
assert(
  completionRankForSymbol("class", "global", "Shader_env") <
    completionRankForSymbol("pure", "current_bound", "Shader_env")
);

console.log("completion helper tests passed");
