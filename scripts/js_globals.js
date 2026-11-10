"use strict";
// Parse classic browser scripts without executing them or reading application configuration.
const fs = require("node:fs");
const acorn = require("../decklab/ui_review/node_modules/acorn");
const scopes = require("../decklab/ui_review/node_modules/eslint-scope");

// Standard callable browser/ECMAScript globals. App helpers must resolve in the page scripts.
const BROWSER_GLOBALS = new Set([
  "Array", "ArrayBuffer", "BigInt", "Blob", "Boolean", "CustomEvent", "Date", "DOMException",
  "DOMParser", "Error", "EvalError", "Event", "File", "FileReader", "Float32Array", "Float64Array",
  "FormData", "Headers", "Image", "Int8Array", "Int16Array", "Int32Array", "IntersectionObserver",
  "Map", "MutationObserver", "Number", "Object", "PointerEvent", "Promise", "RangeError", "RegExp",
  "Request", "ResizeObserver", "Response", "Set", "String", "Symbol", "SyntaxError", "TextDecoder",
  "TextEncoder", "TypeError", "Uint8Array", "Uint8ClampedArray", "Uint16Array", "Uint32Array", "URL",
  "URLSearchParams", "URIError", "WeakMap", "WeakRef", "WeakSet", "AbortController", "AbortSignal",
  "alert", "atob", "btoa", "cancelAnimationFrame", "cancelIdleCallback", "clearInterval", "clearTimeout",
  "confirm", "decodeURI", "decodeURIComponent", "encodeURI", "encodeURIComponent", "fetch",
  "createImageBitmap", "getComputedStyle", "isFinite", "isNaN", "matchMedia", "parseFloat", "parseInt", "print", "prompt",
  "queueMicrotask", "requestAnimationFrame", "requestIdleCallback", "setInterval", "setTimeout", "structuredClone",
]);

function children(node) {
  const found = [];
  for (const [key, value] of Object.entries(node)) {
    if (key === "loc" || key === "range") continue;
    for (const item of Array.isArray(value) ? value : [value]) {
      if (item && typeof item === "object" && typeof item.type === "string") found.push(item);
    }
  }
  return found;
}

function union(a, b) { return new Set([...a, ...b]); }
function intersection(a, b) { return new Set([...a].filter(name => b.has(name))); }

function presentWhen(node, truth) {
  if (node?.type === "UnaryExpression" && node.operator === "!") return presentWhen(node.argument, !truth);
  if (node?.type === "LogicalExpression" && ["&&", "||"].includes(node.operator)) {
    const left = presentWhen(node.left, truth), right = presentWhen(node.right, truth);
    return (node.operator === "&&") === truth ? union(left, right) : intersection(left, right);
  }
  if (node?.type !== "BinaryExpression" || !["===", "==", "!==", "!="].includes(node.operator)) return new Set();
  const typed = node.left.type === "UnaryExpression" ? node.left : node.right;
  const literal = typed === node.left ? node.right : node.left;
  if (typed.operator !== "typeof" || typed.argument?.type !== "Identifier"
      || literal.type !== "Literal" || !["function", "undefined"].includes(literal.value)) return new Set();
  const equal = ["===", "=="].includes(node.operator) === truth;
  return equal === (literal.value === "function") ? new Set([typed.argument.name]) : new Set();
}

function exits(node) {
  if (!node) return false;
  if (["ReturnStatement", "ThrowStatement", "ContinueStatement", "BreakStatement"].includes(node.type)) return true;
  if (node.type === "BlockStatement") return exits(node.body.at(-1));
  return node.type === "IfStatement" && exits(node.consequent) && exits(node.alternate);
}

function guarded(call, name, parents) {
  for (let child = call, parent = parents.get(child); parent; child = parent, parent = parents.get(parent)) {
    if (["FunctionDeclaration", "FunctionExpression", "ArrowFunctionExpression"].includes(parent.type)) break;
    if (["IfStatement", "ConditionalExpression"].includes(parent.type)) {
      if (child === parent.consequent && presentWhen(parent.test, true).has(name)) return true;
      if (child === parent.alternate && presentWhen(parent.test, false).has(name)) return true;
    }
    if (parent.type === "LogicalExpression" && child === parent.right && ["&&", "||"].includes(parent.operator)
        && presentWhen(parent.left, parent.operator === "&&").has(name)) return true;
    if (parent.type === "BlockStatement") {
      const index = parent.body.indexOf(child);
      for (const before of parent.body.slice(0, index)) {
        if (before.type !== "IfStatement") continue;
        if (exits(before.consequent) && presentWhen(before.test, false).has(name)) return true;
        if (exits(before.alternate) && presentWhen(before.test, true).has(name)) return true;
      }
    }
  }
  return false;
}

function audit(files) {
  let text = "";
  const sources = [];
  for (const file of files) {
    if (typeof file.name !== "string" || typeof file.source !== "string") throw new Error("Invalid source input");
    sources.push({name: file.name, start: text.length, source: file.source});
    text += file.source + "\n";
  }
  const locate = position => {
    const file = sources.findLast(file => file.start <= position);
    const prefix = text.slice(file.start, position), lines = prefix.split("\n");
    return {file: file.name, line: lines.length, column: lines.at(-1).length + 1};
  };
  let tree;
  try { tree = acorn.parse(text, {ecmaVersion: "latest", sourceType: "script", ranges: true}); }
  catch (error) { return {issues: [{...locate(error.pos), name: null, message: "JavaScript syntax could not be parsed"}]}; }
  const parents = new Map(), calls = new Map();
  const visit = node => {
    if (["CallExpression", "NewExpression"].includes(node.type) && node.callee.type === "Identifier") {
      calls.set(node.callee, node);
    }
    for (const child of children(node)) { parents.set(child, node); visit(child); }
  };
  visit(tree);
  const manager = scopes.analyze(tree, {ecmaVersion: 2025, sourceType: "script", optimistic: true,
                                       ignoreEval: true, impliedStrict: true});
  const issues = [];
  for (const reference of manager.globalScope.through) {
    const identifier = reference.identifier, call = calls.get(identifier), name = identifier.name;
    if (!call || BROWSER_GLOBALS.has(name) || guarded(call, name, parents)) continue;
    issues.push({...locate(identifier.start), name, message: "Undefined bare call"});
  }
  const top = tree.body.flatMap(node => {
    if (node.type === "FunctionDeclaration") return [node];
    if (node.type !== "VariableDeclaration") return [];
    return node.declarations.filter(declaration => declaration.id.type === "Identifier"
      && ["FunctionExpression", "ArrowFunctionExpression"].includes(declaration.init?.type))
      .map(declaration => ({id: declaration.id, start: declaration.start, body: declaration.init.body}));
  });
  const closer = top.find(node => node.id.name === "closeAllSheets");
  const closeCalls = [];
  if (closer) {
    const findCalls = node => {
      if (node.type === "CallExpression" && node.callee.type === "Identifier") closeCalls.push(node.callee.name);
      for (const child of children(node)) findCalls(child);
    };
    findCalls(closer.body);
  }
  return {issues, sheetClosers: top.filter(node => /^(?:close.*Sheets|.*Close.*Sheets)$/.test(node.id.name))
    .map(node => ({name: node.id.name, ...locate(node.start)})), closeCalls};
}

if (require.main === module) {
  try {
    const input = JSON.parse(fs.readFileSync(0, "utf8"));
    process.stdout.write(JSON.stringify(audit(input.files)));
  } catch (error) {
    process.stderr.write("JavaScript audit failed: " + error.message + "\n");
    process.exitCode = 1;
  }
}
module.exports = {audit};
