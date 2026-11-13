const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const html = fs.readFileSync(path.join(__dirname, 'index.html'), 'utf8');
function extract(name) {
  const marker = `function ${name}(`;
  let start = html.indexOf(marker);
  if (start >= 6 && html.slice(start-6,start) === "async ") start -= 6;
  assert(start >= 0, `Missing ${name}`);
  const brace = html.indexOf('{', start);
  let depth = 0;
  for (let i = brace; i < html.length; i++) {
    if (html[i] === '{') depth++;
    else if (html[i] === '}' && --depth === 0) return html.slice(start, i + 1);
  }
  throw new Error(`Unclosed ${name}`);
}
const sources = (...names) => names.map(extract).join('\n');
const els = new Map();
const $ = id => {
  if (!els.has(id)) els.set(id, {innerHTML:'',textContent:'',disabled:false});
  return els.get(id);
};
const escapeHtml = str => String(str).replaceAll('&','&amp;').replaceAll('<','&lt;')
  .replaceAll('>','&gt;').replaceAll('"','&quot;').replaceAll("'",'&#39;');
const statuses = [], requests = [], downloads = [], revoked = [];
let wrongServerPages = false;
const fakeUrl = {createObjectURL: file => `blob:local/${encodeURIComponent(file.name)}`,
  revokeObjectURL: url => revoked.push(url)};
class FormDataStub {constructor(){this.fields=[];} append(...v){this.fields.push(v);}}
const fetchStub = async (url, options) => {
  requests.push({url, fields: options.body.fields});
  if (url.includes('/pdf-thumbnails')) return {ok:true,json:async()=>({pages:2,images:['data:image/jpeg;base64,AA==','data:image/jpeg;base64,AQ==']})};
  const list = options.body.fields.find(([field])=>field==='sequence_json');
  const pages = list ? JSON.parse(list[1]).length : 8;
  return {ok:true,headers:{get: key => key==='X-Meeting-Pages' ? (wrongServerPages ? null : String(pages)) : null},blob:async()=>({pdf:true})};
};
const source = `
let meetingPack={period:{short_label:'9–15 Nov 2026'}};
let meetingAddingFiles=false, meetingNextFileId=0, meetingAttachments=[], meetingDeckOrder=[];
let meetingGeneratedSlideHtml=Array.from({length:8},(_,i)=>'<article class="mp-slide">Slide '+(i+1)+'</article>');
const MEETING_SLIDE_TITLES=['Title','Executive summary','Activity trend','Municipalities and wards','Candidate participation','Completed and planned','Records to review','Current planning update'];
const MEETING_MAX_FILE_BYTES=25*1024*1024, MEETING_MAX_TOTAL_BYTES=100*1024*1024, MEETING_MAX_PAGES=100;
${sources('meetingDefaultDeck','meetingReorder','meetingSequence','meetingDeckHasChanges',
  'meetingCanDownload','meetingResetDeck','meetingAddFiles','meetingRemovePage','meetingRemoveFile',
  'renderMeetingAttachments','meetingRenderDeck','downloadCombinedMeetingPack')}
return {meetingRenderDeck,meetingReorder,meetingSequence,meetingDeckHasChanges,meetingResetDeck,
  meetingAddFiles,meetingRemovePage,meetingRemoveFile,downloadCombinedMeetingPack,
  getOrder:()=>meetingDeckOrder.slice(),getFiles:()=>meetingAttachments.slice()};`;
const api = new Function('$','escapeHtml','URL','setMeetingStatus','fetch','API_BASE','leaderHeaders',
  'FormData','meetingPeriod','meetingFilename','triggerBlobDownload',source)(
  $,escapeHtml,fakeUrl,(ok,msg)=>statuses.push({ok,msg}),fetchStub,'http://localhost',()=>({Authorization:'Bearer synthetic'}),
  FormDataStub,()=>({from:'2026-11-09',to:'2026-11-15'}),()=> 'Ntsikana_Meeting_Pack.pdf',
  (blob,name)=>downloads.push(name));

(async () => {
  assert(html.indexOf('id="leaderKpis"')<html.indexOf('id="leaderTrendRow"'));
  assert(html.indexOf('id="leaderTrendRow"')<html.indexOf('id="leaderPlannerSection"'),
    'graphs come before current-week calendar');
  assert(html.includes('data-deck-action="remove"'), 'each rendered slide offers X remove');
  assert(html.includes("'dragstart'"), 'desktop drag-and-drop is wired');
  assert(html.includes('id="meetingResetDeckBtn"'), 'reset control is visible');
  assert(html.includes('25 MB each · 100 MB total'), 'larger limits explained');
  api.meetingResetDeck(false);
  assert.equal(api.getOrder().length,8);
  assert.equal($('meetingCombinedPdfBtn').disabled,false,'custom output is available with generated slides only');
  assert.match($('meetingPreview').innerHTML,/Slide 1: Title/);

  const name='<example> & report.pdf';
  await api.meetingAddFiles([{name,size:4000}]);
  assert.equal(api.getFiles().length,1);
  assert.equal(api.getOrder().length,10,'two imported PDF pages follow generated slides');
  assert.match($('meetingPreview').innerHTML,/<img loading="lazy"/,'uploaded page has an independent image');
  assert.match($('meetingPreview').innerHTML,/data:image\/jpeg;base64,AA==/,'first PDF page has its own image');
  assert.match($('meetingPreview').innerHTML,/data:image\/jpeg;base64,AQ==/,'second PDF page has a distinct image');
  assert.match($('meetingPreview').innerHTML,/Open full page/);
  assert.match($('meetingPreview').innerHTML,/&lt;example&gt; &amp; report.pdf/,'untrusted names escaped');
  assert.match($('meetingFileList').innerHTML,/2 of 2 pages included/);
  api.meetingReorder(8,0);
  assert.deepEqual(api.meetingSequence()[0],{kind:'attachment',file:0,page:1});
  api.meetingRemovePage(1); // remove original slide 1
  assert.equal(api.getOrder().includes('g:1'),false);
  assert.match($('meetingFileList').innerHTML,/2 of 2 pages included/);
  api.meetingRemovePage(api.getOrder().indexOf('a:0:2'));
  assert.match($('meetingFileList').innerHTML,/1 of 2 pages included/);
  assert.equal(api.getOrder().length,8);
  assert.equal(api.meetingDeckHasChanges(),true);
  await api.downloadCombinedMeetingPack();
  const call = requests.at(-1);
  assert(call.url.endsWith('/api/leader/meeting-pack/combined.pdf'));
  const sequence = JSON.parse(call.fields.find(([field])=>field==='sequence_json')[1]);
  assert.deepEqual(sequence[0],{kind:'attachment',file:0,page:1});
  assert.equal(sequence.some(x=>x.kind==='generated'&&x.page===1),false,'removed slide excluded');
  assert.equal(sequence.some(x=>x.kind==='attachment'&&x.page===2),false,'removed attachment page excluded');
  assert.equal(call.fields.filter(([field])=>field==='files').length,1);
  assert(downloads.at(-1).endsWith('_customised.pdf'));
  assert(statuses.at(-1).msg.includes('including 1 uploaded PDF pages'));
  assert.match($('meetingCombinedPdfBtn').textContent, /8 pages/);
  const completedDownloads = downloads.length;
  wrongServerPages = true;
  await api.downloadCombinedMeetingPack();
  assert.equal(downloads.length, completedDownloads, 'out-of-date server must never trigger an incomplete download');
  assert.match(statuses.at(-1).msg, /server is out of date/);
  wrongServerPages = false;

  api.meetingResetDeck(false);
  assert.equal(api.getOrder().length,10,'reset restores removed pages');
  api.meetingRemoveFile(0);
  assert.equal(api.getOrder().length,8,'remove PDF excludes all its pages');
  assert.equal(revoked.length,1,'local preview URL released');
  await api.meetingAddFiles([{name:'oversize.pdf',size:26*1024*1024}]);
  assert.equal(api.getFiles().length,0,'oversized PDF refused locally');
  assert(statuses.at(-1).msg.includes('25 MB'));
  console.log('Meeting deck reorder, removal, reset, PDF page previews, limits, and exact export sequence passed');
})().catch(e=>{console.error(e);process.exitCode=1;});
