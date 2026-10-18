(() => {
  'use strict';
  const $=id=>document.getElementById(id),calendar=$('calendar'),input=$('date'),error=$('error'),save=$('save'),saveHint=$('save-hint');
  const picker=$('date-picker-overlay'),pickerTrigger=$('date-picker-trigger');
  const monthNames={
    persian:['فروردین','اردیبهشت','خرداد','تیر','مرداد','شهریور','مهر','آبان','آذر','دی','بهمن','اسفند'],
    gregory:['ژانویه','فوریه','مارس','آوریل','مه','ژوئن','ژوئیه','اوت','سپتامبر','اکتبر','نوامبر','دسامبر'],
    'islamic-umalqura':['محرم','صفر','ربیع‌الاول','ربیع‌الثانی','جمادی‌الاول','جمادی‌الثانی','رجب','شعبان','رمضان','شوال','ذی‌القعده','ذی‌الحجه']
  };
  const numberFa=new Intl.NumberFormat('fa-IR',{useGrouping:false});
  const wheelRowHeight=44;
  const telegram=window.Telegram&&window.Telegram.WebApp;
  if(telegram){telegram.ready();telegram.expand();}
  const today=new DateCalendars.todaySerial();
  let activeCalendar=calendar.value;
  const apiBase=String(window.BOT_API_URL||window.location.origin).replace(/\/+$/,'');
  const initData=telegram&&telegram.initData;
  const canSave=!!(initData||(telegram&&typeof telegram.sendData==='function'));
  let birthdayExists=document.body.dataset.birthdayExists==='true';
  let dateTouched=false;
  function updateSaveLabel(){save.textContent=birthdayExists?'ویرایش تاریخ تولدم':'ثبت تاریخ تولدم';}
  function applySavedBirthday(birthday){
    birthdayExists=!!birthday;
    updateSaveLabel();
    if(!birthday||dateTouched)return;
    let year=DateCalendars.toCalendar('persian',today).year;
    while(year>1){
      try{
        const serial=DateCalendars.fromCalendar('persian',{year,month:birthday.month,day:birthday.day});
        if(serial<=today){
          const selected=DateCalendars.toCalendar(calendar.value,serial);
          input.value=DateCalendars.formatDate(selected);
          updateDateLabel(selected);
          render();
          return;
        }
      }catch{}
      year--;
    }
  }
  updateSaveLabel();
  window.addEventListener('birthday-state',event=>applySavedBirthday(event.detail&&event.detail.birthday));
  save.disabled=!canSave;
  if(canSave)saveHint.textContent='سال برای بررسی تاریخ استفاده می‌شه و فقط ماه و روز ذخیره می‌شن.';
  function todayParts(){return DateCalendars.toCalendar(calendar.value,today);}
  function updateDateLabel(date){pickerTrigger.textContent=date?`${numberFa.format(date.day)} ${monthNames[calendar.value][date.month-1]} ${numberFa.format(date.year)}`:'انتخاب تاریخ';}
  let pickerDate=null;
  function validDays(year,month){
    const days=[];
    for(let day=1;day<=31;day++){
      try{DateCalendars.fromCalendar(calendar.value,{year,month,day});days.push(day);}catch{}
    }
    return days;
  }
  function paintWheel(id,options,selected){
    const wheel=$(id);wheel.replaceChildren();
    options.forEach(option=>{
      const item=document.createElement('button');
      item.type='button';item.className='wheel-option';item.setAttribute('role','option');
      item.dataset.value=String(option.value);item.textContent=option.label;
      item.setAttribute('aria-selected',String(option.value===selected));
      wheel.append(item);
    });
    const index=Math.max(0,options.findIndex(option=>option.value===selected));
    wheel.scrollTop=index*wheelRowHeight;
  }
  function paintPicker(){
    if(!pickerDate)return;
    const range=DateCalendars.calendarRange(calendar.value);
    const years=[];
    for(let year=range.minYear;year<=range.maxYear;year++)years.push({value:year,label:numberFa.format(year)});
    const months=monthNames[calendar.value].map((name,index)=>({value:index+1,label:name}));
    let days=validDays(pickerDate.year,pickerDate.month);
    if(!days.length){pickerDate.day=1;days=validDays(pickerDate.year,pickerDate.month);}
    if(!days.includes(pickerDate.day))pickerDate.day=days[days.length-1];
    paintWheel('year-wheel',years,pickerDate.year);
    paintWheel('month-wheel',months,pickerDate.month);
    paintWheel('day-wheel',days.map(day=>({value:day,label:numberFa.format(day)})),pickerDate.day);
    $('picker-caption').textContent=`${monthNames[calendar.value][pickerDate.month-1]} ${numberFa.format(pickerDate.year)}`;
  }
  function closePicker(){picker.hidden=true;pickerTrigger.setAttribute('aria-expanded','false');document.body.style.overflow='';}
  function openPicker(){
    try{pickerDate=DateCalendars.parse(input.value);}catch{pickerDate=todayParts();}
    paintPicker();picker.hidden=false;pickerTrigger.setAttribute('aria-expanded','true');document.body.style.overflow='hidden';
    $('picker-close').focus();
  }
  function chooseWheel(id,field){
    const wheel=$(id);let timer;
    function settle(){
      const index=Math.max(0,Math.min(wheel.children.length-1,Math.round(wheel.scrollTop/wheelRowHeight)));
      const value=Number(wheel.children[index]?.dataset.value);
      if(!value||pickerDate[field]===value)return;
      pickerDate[field]=value;
      if(field!=='day')paintPicker();
      else wheel.querySelectorAll('.wheel-option').forEach(item=>item.setAttribute('aria-selected',String(Number(item.dataset.value)===value)));
      $('picker-caption').textContent=`${monthNames[calendar.value][pickerDate.month-1]} ${numberFa.format(pickerDate.year)}`;
    }
    wheel.addEventListener('scroll',()=>{clearTimeout(timer);timer=setTimeout(settle,100);},{passive:true});
    wheel.addEventListener('click',event=>{
      const item=event.target.closest('.wheel-option');if(!item)return;
      const index=Array.prototype.indexOf.call(wheel.children,item);
      wheel.scrollTo({top:index*wheelRowHeight,behavior:'smooth'});
    });
  }
  chooseWheel('year-wheel','year');chooseWheel('month-wheel','month');chooseWheel('day-wheel','day');
  function render(){
    error.hidden=true;save.disabled=!canSave;
    try{
      const result=DateCalendars.convert(calendar.value,input.value);
      $('persian-result').textContent=DateCalendars.formatDate(result.persian);
      $('gregorian-result').textContent=DateCalendars.formatDate(result.gregorian);
      $('hijri-result').textContent=DateCalendars.formatDate(result.hijri);
      $('distance').textContent=result.distance;
      const currentPersianYear=DateCalendars.toCalendar('persian',today).year;
      save.disabled=!canSave||result.persian.year>currentPersianYear;
      if(result.persian.year>currentPersianYear&&canSave)saveHint.textContent='سال تولد نمی‌تونه در آینده باشه.';
      else if(canSave)saveHint.textContent='سال فقط برای بررسی تاریخ استفاده می‌شه؛ بات ماه و روز رو نگه می‌داره.';
      save.dataset.persian=JSON.stringify(result.persian);
    }catch(e){
      for(const id of ['persian-result','gregorian-result','hijri-result'])$(id).textContent='—';
      $('distance').textContent='';error.textContent=e.message||'این تاریخ معتبر نیست.';error.hidden=false;
      save.dataset.persian='';save.disabled=true;
    }
  }
  calendar.addEventListener('change',()=>{dateTouched=true;try{const oldDate=DateCalendars.convert(activeCalendar,input.value);input.value=DateCalendars.formatDate(DateCalendars.toCalendar(calendar.value,oldDate.serial));}catch{}activeCalendar=calendar.value;updateDateLabel(DateCalendars.parse(input.value));if(!picker.hidden)openPicker();render();});
  pickerTrigger.addEventListener('click',openPicker);
  $('picker-close').addEventListener('click',closePicker);
  $('picker-cancel').addEventListener('click',closePicker);
  picker.addEventListener('click',event=>{if(event.target===picker)closePicker();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape'&&!picker.hidden)closePicker();});
  $('picker-confirm').addEventListener('click',()=>{
    try{DateCalendars.fromCalendar(calendar.value,pickerDate);dateTouched=true;input.value=DateCalendars.formatDate(pickerDate);updateDateLabel(pickerDate);render();closePicker();}
    catch(e){error.textContent=e.message||'این تاریخ معتبر نیست.';error.hidden=false;}
  });
  input.addEventListener('input',()=>{updateDateLabel(DateCalendars.parse(input.value));render();});
  $('today').addEventListener('click',()=>{dateTouched=true;const current=todayParts();input.value=DateCalendars.formatDate(current);updateDateLabel(current);render();});
  save.addEventListener('click',async()=>{
    if(!canSave)return;
    save.disabled=true;
    try{
      const selected=DateCalendars.convert(calendar.value,input.value);
      const p=selected.persian;
      if(initData){
        const response=await fetch(apiBase+'/api/birthday',{method:'POST',headers:{Authorization:`tma ${initData}`,'Content-Type':'application/json'},body:JSON.stringify({calendar:'solar_hijri',year:p.year,month:p.month,day:p.day})});
        const responseText=await response.text();
        let body={};
        try{body=responseText?JSON.parse(responseText):{};}catch{throw new Error(responseText||'پاسخ API قابل خواندن نیست؛ اتصال بات را بررسی کن.');}
        if(!response.ok)throw new Error(body.error||'ثبت انجام نشد.');
        saveHint.textContent='تاریخ تولدت ذخیره شد.';
        birthdayExists=true;updateSaveLabel();
        save.disabled=false;
        window.dispatchEvent(new CustomEvent('birthday-saved'));
      }else{
        telegram.sendData(JSON.stringify({action:'save_birthday',calendar:'solar_hijri',year:p.year,month:p.month,day:p.day}));
        birthdayExists=true;updateSaveLabel();
      }
    }catch(error){saveHint.textContent=error.message||'ثبت انجام نشد. صفحه رو از داخل بات باز کن و دوباره تلاش کن.';save.disabled=false;}
  });
  input.value=DateCalendars.formatDate(todayParts());updateDateLabel(todayParts());render();
  if(window.currentBirthday)applySavedBirthday(window.currentBirthday);
})();
