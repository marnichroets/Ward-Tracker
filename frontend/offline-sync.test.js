// Regression coverage for offline activity sync. Runs the actual functions
// extracted from the existing candidate page, with no production or network access.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');

function extractFunction(name) {
  const marker = 'function ' + name + '(';
  let start = html.indexOf(marker);
  assert.notEqual(start, -1, name + ' must exist in index.html');
  if (html.slice(start - 6, start) === 'async ') start -= 6;
  const firstBrace = html.indexOf('{', start);
  let depth = 0;
  for (let i = firstBrace; i < html.length; i++) {
    if (html[i] === '{') depth++;
    if (html[i] === '}' && --depth === 0) return html.slice(start, i + 1);
    // Braces inside strings are balanced in these particular functions.
  }
  throw new Error('Unclosed function ' + name);
}

function setup(apiHandler, interactiveHandler = async () => {}) {
  const values = new Map();
  const storage = {
    getItem: key => values.has(key) ? values.get(key) : null,
    setItem: (key, value) => values.set(key, value),
  };
  const functions = [
    'getPendingQueue', 'setPendingQueue', 'queuePendingEntry',
    'updatePendingEntry', 'removePendingEntry', 'trySyncOne', 'mergeWithPending',
  ].map(extractFunction).join('\n');
  return new Function('api', 'postActivityWithDuplicate', 'localStorage',
    "const PENDING_KEY='pendingEntries';\n" + functions +
    '\nreturn {getPendingQueue, queuePendingEntry, updatePendingEntry, trySyncOne, mergeWithPending};'
  )(apiHandler, interactiveHandler, storage);
}

async function run() {
  const entry = {person_id:'candidate-a', week_key:'2026-W46', type:'Canvassing', venue:'Library'};

  // Network loss never erases an activity and automatic retry works later.
  {
    let online = false, attempts = 0;
    const a = setup(async () => {
      attempts++;
      if (!online) throw new Error('offline');
      return {id:'saved'};
    });
    const id = a.queuePendingEntry(entry);
    assert.equal(await a.trySyncOne(id), false);
    assert.equal(a.getPendingQueue().length, 1);
    assert.equal(a.getPendingQueue()[0].syncIssue, undefined);
    online = true;
    assert.equal(await a.trySyncOne(id), true);
    assert.equal(a.getPendingQueue().length, 0);
    assert.equal(attempts, 2);
  }

  // Conflict is preserved for review; automatic retries do not silently
  // override a duplicate. Only a candidate-initiated save may offer it.
  {
    let attempts = 0, interactive = 0;
    const a = setup(async () => {
      attempts++;
      const err = new Error('duplicate');
      err.status = 409;
      err.detail = {duplicate_kind:'exact', message:'Already logged'};
      throw err;
    }, async () => { interactive++; return {id:'new'}; });
    const id = a.queuePendingEntry(entry);
    assert.equal(await a.trySyncOne(id), false);
    assert.equal(a.getPendingQueue()[0].syncIssue, 'duplicate');
    assert.equal(await a.trySyncOne(id), false);
    assert.equal(attempts, 1, 'no repeated background calls for a known conflict');
    assert.equal(interactive, 0, 'background never calls the override');
    assert.equal(await a.trySyncOne(id, true), true);
    assert.equal(interactive, 1);
    assert.equal(a.getPendingQueue().length, 0);
  }

  // A validation rejection is not a connectivity problem. Keep it and
  // let the candidate change it before automatic retry can resume.
  {
    let bad = true, attempts = 0;
    const a = setup(async () => {
      attempts++;
      if (bad) {
        const err = new Error('invalid');
        err.status = 422;
        throw err;
      }
      return {id:'fixed'};
    });
    const id = a.queuePendingEntry(entry);
    assert.equal(await a.trySyncOne(id), false);
    assert.equal(a.getPendingQueue()[0].syncIssue, 'review');
    assert.equal(await a.trySyncOne(id), false);
    assert.equal(attempts, 1);
    a.updatePendingEntry(id, {...entry, venue:'Community Hall'});
    assert.equal(a.getPendingQueue()[0].syncIssue, undefined);
    bad = false;
    assert.equal(await a.trySyncOne(id), true);
    assert.equal(a.getPendingQueue().length, 0);
  }

  // The review marker is also attached to pending edits (not just creates).
  {
    const a = setup(async () => { throw Object.assign(new Error('missing'), {status:404}); });
    const id = a.queuePendingEntry(entry, 'server-entry-id');
    assert.equal(await a.trySyncOne(id), false);
    const merged = a.mergeWithPending([{id:'server-entry-id', venue:'Old'}], a.getPendingQueue());
    assert.equal(merged.length, 1);
    assert.equal(merged[0].syncIssue, 'review');
    assert.equal(merged[0].isPending, true);
  }

  assert.match(html, /Possible duplicate — open to review/);
  assert.match(html, /Not sent — open to check this activity/);
  assert.match(html, /id="duplicateCancel">Not now/);
  assert.match(html, /duplicateCancel'\)\.onclick=\(\)=>resolve\(false\)/);
  console.log('Offline sync review and duplicate conflict tests passed');
}
run().catch(err => { console.error(err); process.exitCode = 1; });
