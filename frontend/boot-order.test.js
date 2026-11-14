const assert = require('assert');
const fs = require('fs');
const path = require('path');

// Regression: opening /#admin (or /#leader) with a saved session runs the
// loader during the initial script evaluation, at the `initialHash` routing
// block. Any top-level `let` that loader assigns before its first `await`
// must already be declared by then, or it throws a temporal-dead-zone
// ReferenceError and the user is wrongly sent back to the PIN prompt (the
// pre-Stage-2 /#admin bug: `smartsheetReviewOpen`).

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');

function extractFunctionSource(src, name) {
  const marker = `function ${name}(`;
  const start = src.indexOf(marker);
  if (start === -1) throw new Error(`could not find function ${name}() in index.html`);
  const braceStart = src.indexOf('{', start);
  let depth = 0;
  let i = braceStart;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) { i++; break; } }
  }
  return src.slice(start, i);
}

const bootIdx = html.indexOf("const initialHash = location.hash");
assert.ok(bootIdx > 0, 'the boot routing block must exist');

const topLevelLets = new Map();
for (const m of html.matchAll(/^let ([A-Za-z_$][\w$]*)/gm)) topLevelLets.set(m[1], m.index);

['loadAdmin', 'loadLeadership'].forEach((loader) => {
  const src = extractFunctionSource(html, loader);
  const syncPrefix = src.slice(0, src.indexOf('await ') === -1 ? src.length : src.indexOf('await '));
  for (const m of syncPrefix.matchAll(/(?:^|[;\s{(])([A-Za-z_$][\w$]*)\s*=(?!=)/g)) {
    const name = m[1];
    if (!topLevelLets.has(name)) continue;
    assert.ok(topLevelLets.get(name) < bootIdx,
      `${loader}() assigns top-level "${name}" before its first await, so "let ${name}" must be declared before the boot routing block`);
  }
});
assert.ok(topLevelLets.get('smartsheetReviewOpen') < bootIdx, 'smartsheetReviewOpen must be declared before boot routing');

console.log('boot-order.test.js OK — boot-time loaders never hit an undeclared let');
