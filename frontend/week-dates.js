(function(root){
  const DAY_ORDER = ['mon','tue','wed','thu','fri','sat','sun'];
  const DAY_LABELS = {mon:'Mon',tue:'Tue',wed:'Wed',thu:'Thu',fri:'Fri',sat:'Sat',sun:'Sun'};
  const DAY_OFFSET = {mon:1,tue:2,wed:3,thu:4,fri:5,sat:6,sun:7};
  const MONTHS = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
  const SAST_TIMEZONE = 'Africa/Johannesburg';

  function pad(n){return n<10?'0'+n:''+n;}
  function dateFromYmd(ymd){
    const parts = ymd.split('-').map(Number);
    return new Date(parts[0], parts[1]-1, parts[2]);
  }
  function ymdFromDate(d){
    return d.getFullYear()+'-'+pad(d.getMonth()+1)+'-'+pad(d.getDate());
  }
  function addDays(d,n){
    const r = new Date(d.getFullYear(), d.getMonth(), d.getDate());
    r.setDate(r.getDate()+n);
    return r;
  }
  function fmtDate(d){
    return d.getDate()+' '+MONTHS[d.getMonth()];
  }
  function fmtYmd(ymd){
    return fmtDate(dateFromYmd(ymd));
  }
  function sastCalendarDate(now){
    const base = now || new Date();
    const parts = new Intl.DateTimeFormat('en-ZA', {
      timeZone:SAST_TIMEZONE, year:'numeric', month:'2-digit', day:'2-digit'
    }).formatToParts(base).reduce((acc, part)=>{
      acc[part.type] = part.value;
      return acc;
    }, {});
    return new Date(Number(parts.year), Number(parts.month)-1, Number(parts.day));
  }
  function currentWeekKey(now){
    const today = sastCalendarDate(now);
    const daysSinceMonday = (today.getDay()+6)%7;
    const monday = addDays(today, -daysSinceMonday);
    return ymdFromDate(addDays(monday, -1));
  }
  function nextWeekKey(weekKey){
    return ymdFromDate(addDays(dateFromYmd(weekKey), 7));
  }
  function previousWeekKey(weekKey){
    return ymdFromDate(addDays(dateFromYmd(weekKey), -7));
  }
  function reportingWeekStart(weekKey){
    return addDays(dateFromYmd(weekKey), 1);
  }
  function reportingWeekEnd(weekKey){
    return addDays(dateFromYmd(weekKey), 7);
  }
  function weekLabel(weekKey){
    return fmtDate(reportingWeekStart(weekKey))+' - '+fmtDate(reportingWeekEnd(weekKey));
  }
  function activityDate(weekKey, day){
    if(!(day in DAY_OFFSET)) throw new Error('Invalid day: '+day);
    return ymdFromDate(addDays(dateFromYmd(weekKey), DAY_OFFSET[day]));
  }
  function dayDateLabel(weekKey, day){
    return fmtYmd(activityDate(weekKey, day));
  }
  function dayWithDate(weekKey, day){
    return (DAY_LABELS[day] || day)+' '+dayDateLabel(weekKey, day);
  }

  const api = {
    DAY_ORDER, DAY_LABELS, DAY_OFFSET, SAST_TIMEZONE,
    addDays, dateFromYmd, ymdFromDate, fmtDate, fmtYmd,
    sastCalendarDate, currentWeekKey, nextWeekKey, previousWeekKey,
    reportingWeekStart, reportingWeekEnd, weekLabel,
    activityDate, dayDateLabel, dayWithDate
  };

  root.WeekDates = api;
  if(typeof module !== 'undefined' && module.exports){
    module.exports = api;
  }
})(typeof globalThis !== 'undefined' ? globalThis : window);
