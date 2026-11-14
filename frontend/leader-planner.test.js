const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const WeekDates = require('./week-dates');

const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
function extract(name){
  const start = html.indexOf(`function ${name}(`);
  assert.notEqual(start, -1, `missing real function ${name}`);
  const open = html.indexOf('{', start);
  let depth=0, end=open;
  for(;end<html.length;end++){
    if(html[end] === '{') depth++;
    if(html[end] === '}' && --depth === 0){end++; break;}
  }
  return html.slice(start,end);
}

// Leadership charts are read first; the calendar follows immediately below them.
assert(html.indexOf('id="leaderDashboardView"') < html.indexOf('id="leaderPlannerSection"'));
assert(html.indexOf('id="leaderKpis"') < html.indexOf('id="leaderTrendRow"'));
assert(html.indexOf('id="leaderTrendRow"') < html.indexOf('id="leaderPlannerSection"'));
assert(html.indexOf('id="leaderPlannerSection"') < html.indexOf('id="leaderWardCoverageSection"'));
assert(html.includes('data-kpi-target="leaderPlannerSection"'));
assert(html.includes('grid-template-columns:repeat(7,minmax(0,1fr))'));

const fakeWeekDates = {...WeekDates, sastCalendarDate:()=>new Date(2026,10,13)};
const currentWeek = WeekDates.currentWeekKey(new Date('2026-11-13T10:00:00Z'));
assert.equal(WeekDates.weekLabelWithYear(currentWeek), '9–15 November 2026');
const elements = {};
function $(id){
  return elements[id] ||= {innerHTML:'',textContent:'',hidden:false,
    setAttribute(name,value){this[name]=value;}};
}
const source = ['weekStartYmd','weekEndYmd','leaderPlannerDateRows',
  'renderLeaderPlannerLoading','renderLeaderPlannerError','renderLeaderPlanner'].map(extract).join('\n');
const api = new Function('WeekDates','$','escapeHtml','activityTimeLabel','CURRENT_WEEK_KEY',
  `let leaderPlannerRows=[]; let leaderPlannerSelectedDay=null;let leaderPlannerFullWeek=false;let leaderPlannerExpanded=false;
  ${source}
  return {filter:leaderPlannerDateRows,render:renderLeaderPlanner,
    fullWeek(v){leaderPlannerFullWeek=v;},expanded(v){leaderPlannerExpanded=v;},
    selection(){return leaderPlannerSelectedDay;},loading:renderLeaderPlannerLoading,error:renderLeaderPlannerError};`
)(fakeWeekDates,$,s=>String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;').replaceAll('"','&quot;'),
  (start,end)=>`${start||'—'} – ${end||'—'}`,currentWeek);

const sample = [
  {activity_date:'2026-11-08',activity:'Sunday last week'},
  {activity_date:'2026-11-09',activity:'House meeting',start_time:'15:00',time_label:'15:00 – 16:00',candidate:'Ayanda',ward:'Ward 1'},
  {activity_date:'2026-11-13',activity:'Door to Door',start_time:'09:00',candidate:'Zintle',municipality:'Amahlathi',ward:'Ward 5',venue:'Clinic'},
  {activity_date:'2026-11-14',activity:'Canvassing <script>alert(1)</script>',start_time:'10:00',candidate:'<img onerror=alert(1)>',ward:'Ward 7',venue:'Hall'},
  {activity_date:'2026-11-14',activity:'Street meeting',start_time:'08:00',candidate:'Busisiwe',ward:'Ward 7'},
  {activity_date:'2026-11-16',activity:'Next week'}
];
const filtered=api.filter({weekly_activity:sample});
assert.equal(filtered.length,4, 'never pull historic or next-week rows into the current week');
assert.equal(filtered[2].activity,'Street meeting','sort events by start time');
assert.equal(filtered[3].activity,'Canvassing <script>alert(1)</script>');
api.render({weekly_activity:sample});
assert.equal(api.selection(),'2026-11-13', 'default to today if activities exist today');
assert.match($('leaderPlannerRange').textContent,/9–15 November 2026/);
assert.match($('leaderPlannerTotals').textContent,/4 recorded · 3 today or upcoming/);
assert.equal(($('leaderPlannerDays').innerHTML.match(/data-planner-day=/g)||[]).length,7);
assert.match($('leaderPlannerEntries').innerHTML,/Door to Door/);
assert(!$('leaderPlannerEntries').innerHTML.includes('Street meeting'),'selected day shows only that day');
assert.match($('leaderPlannerViewAll').textContent,/View full week/);
api.fullWeek(true);api.render({weekly_activity:sample});
assert.match($('leaderPlannerEntries').innerHTML,/Street meeting/);
assert.match($('leaderPlannerEntries').innerHTML,/&lt;script&gt;/,'escape untrusted activity names');
assert.match($('leaderPlannerEntries').innerHTML,/&lt;img/,'escape untrusted candidate names');
assert(!$('leaderPlannerEntries').innerHTML.includes('<script>'));
api.render({weekly_activity:[]});
assert.match($('leaderPlannerEntries').innerHTML,/No activities recorded for this week/);
api.error();
assert.match($('leaderPlannerEntries').innerHTML,/Could not load/);
api.loading();
assert.match($('leaderPlannerEntries').innerHTML,/Loading activities/);

// Regression: navigation through an old reporting week must query the CURRENT
// week for the separate planner, keeping the selected municipality/ward/person.
assert.match(html,/leaderQuery\(\{weekKey: CURRENT_WEEK_KEY, weeks: 1\}\)/);
assert.match(html,/renderLeaderPlanner\(currentWeek\)/);
console.log('leader current-week planner tests passed');
