(() => {
  'use strict';
  const $=id=>document.getElementById(id),calendar=$('calendar'),input=$('date'),error=$('error'),save=$('save'),saveHint=$('save-hint');
  const telegram=window.Telegram&&window.Telegram.WebApp;
  if(telegram){telegram.ready();telegram.expand();}
  const today=new DateCalendars.todaySerial();
  let activeCalendar=calendar.value;
  const hasSendData=!!(telegram&&typeof telegram.sendData==='function');
  save.disabled=!hasSendData;
  if(hasSendData)saveHint.textContent='سال برای بررسی تاریخ استفاده می‌شه و فقط ماه و روز ذخیره می‌شن.';
  function todayParts(){return DateCalendars.toCalendar(calendar.value,today);}
  function render(){
    error.hidden=true;save.disabled=!hasSendData;
    try{
      const result=DateCalendars.convert(calendar.value,input.value);
      $('persian-result').textContent=DateCalendars.formatDate(result.persian);
      $('gregorian-result').textContent=DateCalendars.formatDate(result.gregorian);
      $('hijri-result').textContent=DateCalendars.formatDate(result.hijri);
      $('distance').textContent=result.distance;
      const currentPersianYear=DateCalendars.toCalendar('persian',today).year;
      save.disabled=!hasSendData||result.persian.year>currentPersianYear;
      if(result.persian.year>currentPersianYear&&hasSendData)saveHint.textContent='سال تولد نمی‌تونه در آینده باشه.';
      else if(hasSendData)saveHint.textContent='سال فقط برای بررسی تاریخ استفاده می‌شه؛ بات ماه و روز رو نگه می‌داره.';
      save.dataset.persian=JSON.stringify(result.persian);
    }catch(e){
      for(const id of ['persian-result','gregorian-result','hijri-result'])$(id).textContent='—';
      $('distance').textContent='';error.textContent=e.message||'این تاریخ معتبر نیست.';error.hidden=false;
      save.dataset.persian='';save.disabled=true;
    }
  }
  calendar.addEventListener('change',()=>{try{const oldDate=DateCalendars.convert(activeCalendar,input.value);input.value=DateCalendars.formatDate(DateCalendars.toCalendar(calendar.value,oldDate.serial));}catch{}activeCalendar=calendar.value;render();});
  input.addEventListener('input',render);
  $('today').addEventListener('click',()=>{input.value=DateCalendars.formatDate(todayParts());render();});
  save.addEventListener('click',()=>{
    if(!hasSendData)return;
    try{const p=JSON.parse(save.dataset.persian);telegram.sendData(JSON.stringify({action:'save_birthday',calendar:'solar_hijri',year:p.year,month:p.month,day:p.day}));}
    catch{saveHint.textContent='ثبت انجام نشد. صفحه رو از داخل بات باز کن و دوباره تلاش کن.';}
  });
  input.value=DateCalendars.formatDate(todayParts());render();
})();
