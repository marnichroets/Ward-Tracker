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
  const elements = {cFormEyebrow:{},cFormTitle:{},cLegacyHelper:{},cSaveDraftBtn:{},cSaveBtn:{}};
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
assert.strictEqual(mode.cLegacyHelper.hidden,true);
mode=campaignMode({submission_status:'submitted',completeness:{ready:false}},true);
assert.strictEqual(mode.cFormEyebrow.textContent,'Complete campaign details');
assert.strictEqual(mode.cLegacyHelper.hidden,false);
assert.deepStrictEqual([mode.cSaveDraftBtn.hidden,mode.cSaveBtn.textContent,mode.cSaveBtn.hidden],[true,'Save Changes',false]);
assert.ok(html.includes("if(status==='submitted'&&!legacyCompletion)"), 'legacy submitted campaigns must allow partial Save Changes progress');

const missingSource = html.match(/function campaignMissing\(data\)\{[\s\S]*?\n\}/)[0];
function missingFor(data, plan, minimum=2, municipality='Amahlathi') {
  const config={campaign_themes:['Crime'],planned_activity_groups:[{values:['Community Crime Patrol']}]};
  return new Function('data','config','municipality','plan','minimum',`let campaignConfig=config;let campaignFormMunicipality=municipality;let campaignPlan=plan;function recommendedPlanMinimum(){return minimum;}${missingSource};return campaignMissing(data);`)(data,config,municipality,plan,minimum);
}
const completeCampaign={name:'Safer Streets',objective:'Reduce crime',problem_description:'Unsafe streets',solution:'Community patrols',wards:['Ward 7'],start_date:'2026-09-15',end_date:'2026-09-21',campaign_theme:'Crime',purpose:'tackling_problem',includes_criticism:false,campaign_message:'Work together for safer streets.'};
const completePlan=[
  {date:'2026-09-16',time:'10:00',activity_type:'Community Crime Patrol',area:''},
  {date:'2026-09-18',time:'14:00',activity_type:'Community Crime Patrol',area:''},
];
assert.deepStrictEqual(missingFor(completeCampaign,completePlan),[], 'all official fields plus the required plan must be complete');
assert.ok(missingFor({...completeCampaign,campaign_theme:'Select theme'},completePlan).includes('Campaign theme'), 'theme placeholder must remain incomplete');
assert.ok(missingFor({...completeCampaign,objective:'   '},completePlan).includes('Objective'), 'whitespace must remain incomplete');
assert.ok(missingFor(completeCampaign,[completePlan[0],{date:'2026-09-18',time:'',activity_type:'Select activity'}]).includes('planned activities (1 of 2)'), 'partial plan rows must not count toward the minimum');
assert.ok(missingFor(completeCampaign,[],2).includes('planned activities (0 of 2)'), 'legacy activity types cannot replace detailed plan rows');
assert.ok(missingFor(completeCampaign,completePlan,2,'').includes('Municipality'), 'canonical municipality is mandatory');

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
