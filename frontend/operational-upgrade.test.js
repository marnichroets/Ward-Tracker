const assert = require('assert');
const fs = require('fs');
const path = require('path');

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');

// Candidate form stays on one page and exposes the operational controls.
for (const text of [
  'Campaign Basics', 'Campaign Message', 'People Helping', 'Planned Activities',
  'Save Draft', 'Submit Campaign', 'Continue Campaign', 'Ready to submit',
  'A campaign must run for at least 7 days.', '+ Add another person', '+ Add Activity',
]) assert.ok(html.includes(text), `missing candidate campaign UI: ${text}`);

// Planned and completed are deliberately rendered as separate sections.
assert.ok(html.includes('<h2>Planned Activities</h2>'));
assert.ok(html.includes('<h2>Completed Activities</h2>'));
assert.ok(html.includes('Recommended minimum:'));
assert.ok(html.includes('<select id="cPlanTime"'), 'planned time must use a mobile-friendly select');
assert.ok(html.includes("populateTimeSelect($('cPlanTime')"), 'planned time must reuse the shared time options');
assert.ok(html.includes('of ${minimum} planned activities added'), 'plan progress must show current count against minimum');
assert.ok(html.includes('planned activities · Minimum reached'), 'satisfied plan progress must say minimum reached');
assert.ok(!html.includes('What activities are you planning?'), 'candidate must not enter planned activity types twice');
assert.ok(html.includes('[hidden]{display:none !important;}'), 'hidden campaign actions must not be overridden by button display styling');
assert.ok(html.includes('.btn.primary{background:var(--gold);color:var(--navy) !important;}'), 'primary action text must retain high contrast');

const modeSource = html.match(/function renderCampaignFormMode\([\s\S]*?\n\}/)[0];
function campaignMode(initial, hasServerRecord) {
  const elements = {cFormEyebrow:{},cFormTitle:{},cSaveDraftBtn:{},cSaveBtn:{}};
  new Function('elements','initial','hasServerRecord',`${modeSource};function $(id){return elements[id];}renderCampaignFormMode(initial,hasServerRecord);`)(elements,initial,hasServerRecord);
  return elements;
}
let mode=campaignMode({},false);
assert.deepStrictEqual([mode.cSaveDraftBtn.textContent,mode.cSaveDraftBtn.hidden,mode.cSaveBtn.textContent,mode.cSaveBtn.hidden],['Save Draft',false,'Submit Campaign',false]);
assert.strictEqual(mode.cFormEyebrow.textContent,'New campaign');
mode=campaignMode({submission_status:'draft'},true);
assert.deepStrictEqual([mode.cSaveDraftBtn.textContent,mode.cSaveDraftBtn.hidden,mode.cSaveBtn.textContent,mode.cSaveBtn.hidden],['Save Draft',false,'Submit Campaign',false]);
assert.strictEqual(mode.cFormEyebrow.textContent,'Continue campaign');
mode=campaignMode({submission_status:'submitted'},true);
assert.deepStrictEqual([mode.cSaveDraftBtn.hidden,mode.cSaveBtn.textContent,mode.cSaveBtn.hidden],[true,'Save Changes',false]);
assert.strictEqual(mode.cFormEyebrow.textContent,'Edit campaign');

// Coordinator campaign capture is manual, copyable and explicit about sync.
for (const text of [
  'Official Campaign Capture Information', 'External Capture Checklist',
  'Campaign Manager', 'Constituency Calendar', 'Manual tracking only',
  'Campaign updated after official capture — review required', 'Official Record Updated',
  'Change History', 'Copy',
]) assert.ok(html.includes(text), `missing coordinator capture UI: ${text}`);

// Both duplicate paths require an intentional user choice.
for (const text of [
  'This activity appears to have already been logged.', 'Possible duplicate found',
  'View Existing Activity', 'Review Existing Activity', 'Submit Anyway',
  'A similar campaign already exists.', 'View Existing Campaign', 'Create Anyway',
  'Confirm Duplicate', 'Not a Duplicate',
]) assert.ok(html.includes(text), `missing duplicate workflow UI: ${text}`);

// One canonical display helper handles recorded and missing historical times.
assert.ok(html.includes("return start||end||'Time not recorded';"));
assert.ok(html.includes("a.time_label||activityTimeLabel(a.start_time,a.end_time)"));
assert.ok(!html.includes('activity_time:'), 'frontend must not create a second activity-time field');

console.log('operational upgrade frontend tests passed');
