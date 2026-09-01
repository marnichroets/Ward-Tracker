const assert = require('assert');
const fs = require('fs');
const path = require('path');

const {ACTIVITY_OPTIONS, CATEGORIES, CATEGORY_LABELS} = require('./smartsheet-activities');

const seen = new Set(ACTIVITY_OPTIONS.map(v => v.toLowerCase()));
assert.strictEqual(seen.size, ACTIVITY_OPTIONS.length, 'activity labels should not be duplicated');
assert.ok(ACTIVITY_OPTIONS.includes('House Meeting'));
assert.ok(ACTIVITY_OPTIONS.includes('Street Meeting'));
assert.ok(ACTIVITY_OPTIONS.includes('Blue Wave'));
assert.strictEqual(CATEGORIES.CANVASSING, 'CANVASSING');
assert.strictEqual(CATEGORIES.PUBLIC_STREET_MEETING, 'PUBLIC_STREET_MEETING');
assert.strictEqual(CATEGORIES.PRESENCE, 'PRESENCE');
assert.strictEqual(CATEGORY_LABELS.NEEDS_REVIEW, 'Needs Review');

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
assert.ok(html.includes('id="fDate"'), 'candidate form should include a date picker');
assert.ok(html.includes('id="fStartTime"'), 'candidate form should include start time');
assert.ok(html.includes('id="fEndTime"'), 'candidate form should include end time');
assert.ok(html.includes('id="fActivity"'), 'candidate form should include one activity select');
assert.ok(html.includes('id="fVenue"'), 'candidate form should include venue / area');
assert.ok(!html.includes('id="typeChips"'), 'candidate form should not use category/type chips');

const inlineScripts = [...html.matchAll(/<script(?![^>]*\bsrc=)[^>]*>([\s\S]*?)<\/script>/gi)];
inlineScripts.forEach((match) => {
  new Function(match[1]);
});

console.log('smartsheet activity frontend tests passed');
