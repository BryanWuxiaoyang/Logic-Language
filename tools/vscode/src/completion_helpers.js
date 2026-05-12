"use strict";

function isClassName(name) {
  return /^[A-Z][A-Za-z0-9_']*$/.test(name || "");
}

function isSymbolNameCharacter(char) {
  return /[A-Za-z0-9_']/.test(char || "");
}

function isSymbolName(name) {
  return /^[A-Za-z_][A-Za-z0-9_']*$/.test(name || "");
}

function isLiteralQuoteStart(text, index) {
  if (index < 0 || index >= String(text || "").length) {
    return false;
  }
  const current = text[index];
  if (current === "\"") {
    return true;
  }
  if (current !== "'") {
    return false;
  }
  const previous = index > 0 ? text[index - 1] : "";
  return !(/[A-Za-z0-9]/.test(previous) || previous === "_" || previous === "$" || previous === "'");
}

function lineStateAt(text, character) {
  let quote = "";
  let escaped = false;

  for (let index = 0; index < character; index += 1) {
    const current = text[index];
    if (quote) {
      if (escaped) {
        escaped = false;
        continue;
      }
      if (current === "\\") {
        escaped = true;
        continue;
      }
      if (current === quote) {
        quote = "";
      }
      continue;
    }

    if (current === "#") {
      return { inComment: true, inQuote: false };
    }
    if (isLiteralQuoteStart(text, index)) {
      quote = current;
    }
  }

  return { inComment: false, inQuote: quote !== "" };
}

function isCapitalHeadPrefix(prefix) {
  return /^[A-Z]/.test(prefix || "");
}

function stripOuterTuple(text) {
  const trimmed = String(text || "").trim();
  if (trimmed.length >= 2 && trimmed.startsWith("(") && trimmed.endsWith(")")) {
    return trimmed.slice(1, -1).trim();
  }
  return trimmed;
}

function parseSignatureTerms(text) {
  const body = stripOuterTuple(text);
  if (!body) {
    return [];
  }
  return body
    .split(",")
    .map((part) => part.trim())
    .filter((part) => isSymbolName(part));
}

function parseBinderNames(stripped) {
  if (!String(stripped || "").startsWith("|") || String(stripped || "").startsWith("|-") || String(stripped || "").includes(":")) {
    return [];
  }
  const body = String(stripped || "").slice(1).trim();
  if (!body) {
    return [];
  }
  const equalsIndex = body.indexOf("=");
  if (equalsIndex >= 0) {
    const lhs = body.slice(0, equalsIndex).trim();
    return isSymbolName(lhs) ? [lhs] : [];
  }
  const membershipMatch = body.match(/^([A-Za-z_][A-Za-z0-9_']*)\s*(?:∈|\\in\b)/);
  if (membershipMatch) {
    return [membershipMatch[1]];
  }
  const imageArrowIndex = body.indexOf("=>");
  if (imageArrowIndex >= 0) {
    return parseSignatureTerms(body.slice(0, imageArrowIndex).trim());
  }
  if (/[~=><(){}[\]]/.test(body)) {
    return [];
  }
  const names = parseSignatureTerms(body);
  return names.length > 0 ? names : [];
}

function completionFilterText(name, prefix) {
  if (String(name || "").startsWith("_") && !String(prefix || "").startsWith("_")) {
    return name.replace(/^_/, "");
  }
  return name;
}

function completionRankForSymbol(type, scope, prefix) {
  if (isCapitalHeadPrefix(prefix)) {
    if (type === "class") {
      return 1;
    }
    if (scope === "current_bound") {
      return 2;
    }
    if (scope === "ancestor_bound") {
      return 3;
    }
    return type === "func" || type === "pred" ? 4 : 5;
  }
  if (scope === "current_bound") {
    return 1;
  }
  if (scope === "ancestor_bound") {
    return 2;
  }
  if (type === "class") {
    return 3;
  }
  return type === "func" || type === "pred" ? 4 : 5;
}

function classMethodFirstParamCompletionContext(lineText, character, activeClassName) {
  const beforeCursor = String(lineText || "").slice(0, character);
  const match = beforeCursor.match(
    /^(?<prefix>\s*(?:\|\s*)?(?:(?<className>[A-Za-z_][A-Za-z0-9_']*)::|::)(?<method>[^\s:]+):)(?<signature>.*)$/
  );
  if (!match || !match.groups) {
    return undefined;
  }

  const signature = match.groups.signature || "";
  if (signature.includes("=>") || signature.includes(",")) {
    return undefined;
  }

  const className = match.groups.className || activeClassName;
  if (!className || !isClassName(className)) {
    return undefined;
  }

  const receiverName = `_${className.toLowerCase()}`;
  const signatureStart = match.groups.prefix.length;
  const leadingWhitespace = signature.match(/^\s*/)[0];
  const firstParamStart = signatureStart + leadingWhitespace.length;
  const hasExistingSpace = leadingWhitespace.length > 0;
  const hasOpeningParen = beforeCursor[firstParamStart] === "(";
  const hasFirstParamText = signature.length > leadingWhitespace.length;

  let replaceStart;
  let insertText;
  if (hasOpeningParen) {
    replaceStart = firstParamStart;
    insertText = `(${receiverName}`;
  } else if (hasFirstParamText) {
    replaceStart = firstParamStart;
    insertText = hasExistingSpace ? `(${receiverName}` : ` (${receiverName}`;
  } else {
    replaceStart = character;
    insertText = hasExistingSpace ? `(${receiverName}` : ` (${receiverName}`;
  }

  let replaceEnd = character;
  while (replaceEnd < lineText.length && isSymbolNameCharacter(lineText[replaceEnd])) {
    replaceEnd += 1;
  }

  return {
    label: `(${receiverName}`,
    insertText,
    filterText: receiverName,
    replaceStart,
    replaceEnd,
    receiverName,
    className
  };
}

module.exports = {
  classMethodFirstParamCompletionContext,
  completionFilterText,
  completionRankForSymbol,
  isClassName,
  isLiteralQuoteStart,
  lineStateAt,
  parseBinderNames,
  parseSignatureTerms
};
