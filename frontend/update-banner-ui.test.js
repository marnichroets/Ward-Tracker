// Exercises the REAL showUpdateBanner() function extracted out of
// index.html's <script> (not a reimplementation) against a small but
// *correct* fake DOM (getElementById only finds what was actually
// appended, unlike script-load.test.js's auto-vivifying stub — needed here
// because this function's own "don't duplicate" guard depends on that).
const assert = require('assert');
const fs = require('fs');
const path = require('path');
const vm = require('vm');

function extractFunctionSource(src, name) {
  const marker = `function ${name}(`;
  const start = src.indexOf(marker);
  if (start === -1) throw new Error(`could not find function ${name}`);
  let depth = 0, i = src.indexOf('{', start);
  const bodyStart = i;
  for (; i < src.length; i++) {
    if (src[i] === '{') depth++;
    else if (src[i] === '}') { depth--; if (depth === 0) { i++; break; } }
  }
  return src.slice(start, i);
}

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
const scriptMatch = html.match(/<script>([\s\S]*?)<\/script>/);
const pageScriptSrc = scriptMatch[1];
const showUpdateBannerSrc = extractFunctionSource(pageScriptSrc, 'showUpdateBanner');

function makeNode(tag) {
  let html = '';
  const node = {
    tag, id: '', className: '', children: [], onclick: null,
    // _innerIdNodes holds lightweight stand-ins for elements the production
    // code builds via an innerHTML string (e.g. the banner's own Update/
    // Dismiss buttons) rather than real appendChild calls — a minimal
    // stand-in for what a real HTML parser would create, since this stub
    // has no actual parser.
    _innerIdNodes: {},
    setAttribute() {}, getAttribute() { return null; },
    appendChild(child) { node.children.push(child); return child; },
    remove() {
      const parent = node._parent;
      if (parent) parent.children = parent.children.filter((c) => c !== node);
    },
  };
  Object.defineProperty(node, 'innerHTML', {
    get() { return html; },
    set(value) {
      html = value;
      node._innerIdNodes = {};
      const re = /id="([^"]+)"/g;
      let m;
      while ((m = re.exec(value))) {
        node._innerIdNodes[m[1]] = { id: m[1], onclick: null, remove() { bar_remove(node, m[1]); } };
      }
    },
  });
  function bar_remove(ownerNode, id) { delete ownerNode._innerIdNodes[id]; }
  return node;
}

function makeDom() {
  const body = makeNode('body');
  function findById(root, id) {
    if (root.id === id) return root;
    if (root._innerIdNodes && root._innerIdNodes[id]) return root._innerIdNodes[id];
    for (const child of root.children) {
      const found = findById(child, id);
      if (found) return found;
    }
    return null;
  }
  const documentStub = {
    body,
    createElement(tag) { return makeNode(tag); },
    getElementById(id) { return findById(body, id); },
  };
  const realAppendChild = body.appendChild;
  body.appendChild = function (child) { child._parent = body; return realAppendChild(child); };
  return documentStub;
}

function run(document) {
  const sandbox = { document, console };
  sandbox.globalThis = sandbox;
  vm.createContext(sandbox);
  vm.runInContext(`${showUpdateBannerSrc}\nthis.showUpdateBanner = showUpdateBanner;`, sandbox);
  return sandbox.showUpdateBanner;
}

// --- A genuine update becomes available: the banner must appear with an Update button ---
{
  const document = makeDom();
  const showUpdateBanner = run(document);
  const posted = [];
  const fakeWorker = { postMessage(msg) { posted.push(msg); } };

  showUpdateBanner(fakeWorker);

  const bar = document.getElementById('updateBanner');
  assert.ok(bar, 'showUpdateBanner must add a banner element to the page');
  assert.ok(bar.innerHTML.includes("Ward Tracker has been updated"), 'banner must tell the candidate an update is ready, not force anything');
  assert.ok(bar.innerHTML.includes('Update'), 'banner must offer an explicit Update button');

  const btn = document.getElementById('updateBannerBtn');
  assert.strictEqual(typeof btn.onclick, 'function', 'Update button must be wired');
  btn.onclick();
  assert.deepStrictEqual(posted, ['SKIP_WAITING'], 'clicking Update must message the waiting worker to activate — never an automatic/forced reload');

  const closeBtn = document.getElementById('updateBannerClose');
  assert.strictEqual(typeof closeBtn.onclick, 'function', 'dismiss control must be wired so the banner never blocks the candidate');
  closeBtn.onclick();
  assert.strictEqual(document.getElementById('updateBanner'), null, 'dismissing must remove the banner');
}

// --- Calling it twice (e.g. two update-found events) must not duplicate the banner ---
{
  const document = makeDom();
  const showUpdateBanner = run(document);
  showUpdateBanner({ postMessage() {} });
  showUpdateBanner({ postMessage() {} });
  assert.strictEqual(document.body.children.length, 1, 'showUpdateBanner must never stack a second banner on top of an existing one');
}

console.log('update banner UI tests passed');
