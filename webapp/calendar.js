/* Pure calendar conversion helpers, using the browser's ICU calendar data. */
(() => {
  'use strict';
  const formatters = new Map();
  const dayMs = 86400000;
  const MIN_DAY = Date.UTC(1800, 0, 1) / dayMs;
  const MAX_DAY = Date.UTC(2201, 0, 1) / dayMs;
  function formatter(calendar) {
    if (!formatters.has(calendar)) formatters.set(calendar, new Intl.DateTimeFormat('en-US-u-nu-latn-ca-' + calendar, {calendar, numberingSystem:'latn', timeZone:'UTC', year:'numeric', month:'numeric', day:'numeric'}));
    return formatters.get(calendar);
  }
  function parts(calendar, serial) {
    const values = {};
    for (const part of formatter(calendar).formatToParts(new Date(serial * dayMs + 43200000))) if (['year','month','day'].includes(part.type)) values[part.type] = Number(part.value);
    return {year:values.year, month:values.month, day:values.day};
  }
  function compare(a,b) { return a.year-b.year || a.month-b.month || a.day-b.day; }
  function fromCalendar(calendar, target) {
    let lo=MIN_DAY, hi=MAX_DAY;
    while(lo<hi){const mid=Math.floor((lo+hi)/2);if(compare(parts(calendar,mid),target)<0)lo=mid+1;else hi=mid;}
    const found=parts(calendar,lo);
    if(compare(found,target)!==0) throw new RangeError('این تاریخ در تقویم انتخابی وجود نداره.');
    return lo;
  }
  function toCalendar(calendar, serial) { return parts(calendar,serial); }
  function calendarRange(calendar) { return {minYear:parts(calendar,MIN_DAY).year+1,maxYear:parts(calendar,MAX_DAY-1).year-1}; }
  function parse(value) {
    const normalized=String(value).replace(/[۰-۹]/g,c=>String('۰۱۲۳۴۵۶۷۸۹'.indexOf(c))).replace(/[٠-٩]/g,c=>String('٠١٢٣٤٥٦٧٨٩'.indexOf(c))).trim();
    const m=normalized.match(/^\s*(\d{1,4})\s*[\/.-]\s*(\d{1,2})\s*[\/.-]\s*(\d{1,2})\s*$/);
    if(!m) throw new RangeError('تاریخ رو به شکل سال/ماه/روز وارد کن.');
    return {year:Number(m[1]),month:Number(m[2]),day:Number(m[3])};
  }
  function serialToGregorian(serial){const d=new Date(serial*dayMs+43200000);return {year:d.getUTCFullYear(),month:d.getUTCMonth()+1,day:d.getUTCDate()};}
  function formatDate(p){return [p.year,p.month,p.day].map((x,i)=>String(x).padStart(i?2:4,'0')).join('/').replace(/\d/g,d=>'۰۱۲۳۴۵۶۷۸۹'[d]);}
  function todaySerial(){const now=new Date(), local=new Intl.DateTimeFormat('en-CA',{timeZone:'Asia/Tehran',year:'numeric',month:'2-digit',day:'2-digit'}).formatToParts(now),p={};for(const x of local)if(x.type!=='literal')p[x.type]=Number(x.value);return Date.UTC(p.year,p.month-1,p.day)/dayMs;}
  function daysInGregorianMonth(y,m){return new Date(Date.UTC(y,m,0)).getUTCDate();}
  function addMonths(date,count){const monthIndex=date.month-1+count,year=date.year+Math.floor(monthIndex/12),month=((monthIndex%12)+12)%12+1;return {year,month,day:Math.min(date.day,daysInGregorianMonth(year,month))};}
  function ageSince(birth,today){let years=today.year-birth.year;const anniversary={year:birth.year+years,month:birth.month,day:Math.min(birth.day,daysInGregorianMonth(birth.year+years,birth.month))};if(compare(today,anniversary)<0)years--;const afterYears={year:birth.year+years,month:birth.month,day:Math.min(birth.day,daysInGregorianMonth(birth.year+years,birth.month))};let months=(today.year-afterYears.year)*12+today.month-afterYears.month;let monthMark=addMonths(afterYears,months);if(compare(monthMark,today)>0){months--;monthMark=addMonths(afterYears,months);}const days=Date.UTC(today.year,today.month-1,today.day)/dayMs-Date.UTC(monthMark.year,monthMark.month-1,monthMark.day)/dayMs;return {years,months,days};}
  function difference(serial,today){const delta=serial-today;if(delta===0)return 'این تاریخ، امروزِ.';if(delta>0)return `${delta.toLocaleString('fa-IR')} روز تا این تاریخ مونده.`;const a=ageSince(serialToGregorian(serial),serialToGregorian(today));return `${Math.abs(delta).toLocaleString('fa-IR')} روز از این تاریخ گذشته · سن: ${a.years.toLocaleString('fa-IR')} سال و ${a.months.toLocaleString('fa-IR')} ماه و ${a.days.toLocaleString('fa-IR')} روز.`;}
  function convert(calendar,value){const date=typeof value==='string'?parse(value):value;if(!Number.isInteger(date.year)||date.year<1||date.year>9999||!Number.isInteger(date.month)||!Number.isInteger(date.day))throw new RangeError('تاریخ واردشده معتبر نیست.');const serial=fromCalendar(calendar,date);return {serial,gregorian:toCalendar('gregory',serial),persian:toCalendar('persian',serial),hijri:toCalendar('islamic-umalqura',serial),distance:difference(serial,todaySerial())};}
  window.DateCalendars={convert,formatDate,fromCalendar,toCalendar,parse,todaySerial,calendarRange};
})();
