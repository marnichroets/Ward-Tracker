const assert = require('assert');
const fs = require('fs');
const path = require('path');
const WeekDates = require('./week-dates');
const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
function functionSource(name){
  const start=html.indexOf('function '+name+'(');
  assert.ok(start>=0, 'missing '+name);
  const b=html.indexOf('{',start);let d=0,i=b;
  for(;i<html.length;i++){if(html[i]==='{') d++; if(html[i]==='}' && !--d){i++;break;}}
  return html.slice(start,i);
}
const chart=new Function('WeekDates','escapeHtml',
  `${functionSource('weeklyCategoryChartData')}
   ${functionSource('trendLineSvg')}
   return {weeklyCategoryChartData,trendLineSvg};`)(WeekDates,
  new Function(functionSource('escapeHtml')+';return escapeHtml')());
const sample=[
 {week_key:'2026-11-08',start_date:'2026-11-09',label:'9 Nov–15 Nov',total_activities:6,
  activity_types:{'Door to Door':3,'Public Meeting':2,'Social Media':1}},
 {week_key:'2026-11-15',start_date:'2026-11-16',label:'16 Nov–22 Nov',total_activities:4,
  activity_types:{'Door to Door':1,'Public Meeting':1,'House Meeting':2}},
];
const overview=chart.weeklyCategoryChartData(sample, '');
assert.deepStrictEqual(overview.data.map(row=>row.reduce((a,b)=>a+b,0)), [6,4]);
assert.deepStrictEqual(chart.weeklyCategoryChartData(sample,'Public Meeting').data, [[2],[1]]);
assert.ok(overview.names.includes('House Meeting'));
const htmlChart=chart.trendLineSvg(sample,overview.categories,overview.data,650);
assert.ok(htmlChart.includes('Weekly activity trends by type'));
assert.ok(htmlChart.includes('data-leader-week="2026-11-08"'));
assert.ok(!htmlChart.includes('NaN') && !htmlChart.includes('undefined'));
assert.ok(/value="52"[^>]*>1 year/.test(html),'one-year reporting option');
assert.ok(/value="8"[^>]*>2 months/.test(html),'two-month reporting option');
console.log('Weekly category trend figures, period lengths and SVG smoke checks passed');
