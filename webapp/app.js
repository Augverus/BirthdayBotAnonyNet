(() => {
  'use strict';
  const $=id=>document.getElementById(id),calendar=$('calendar'),input=$('date'),error=$('error'),save=$('save'),saveHint=$('save-hint');
  const monthNames={
    persian:['فروردین','اردیبهشت','خرداد','تیر','مرداد','شهریور','مهر','آبان','آذر','دی','بهمن','اسفند'],
    gregory:['ژانویه','فوریه','مارس','آوریل','مه','ژوئن','جولای','آگوست','سپتامبر','اکتبر','نوامبر','دسامبر'],
    'islamic-umalqura':['محرّم','صفر','ربيع الأول','ربيع الآخر','جمادى الأولى','جمادى الآخرة','رجب','شعبان','رمضان','شوّال','ذو القعدة','ذو الحجة']
  };
  const calendarNames={persian:'شمسی',gregory:'میلادی','islamic-umalqura':'قمری ام‌القری'};
  const numberFa=new Intl.NumberFormat('fa-IR',{useGrouping:false});
  const telegram=window.Telegram&&window.Telegram.WebApp;
  if(telegram){telegram.ready();telegram.expand();}
  const today=new DateCalendars.todaySerial();
  let dateParts=null;
  const apiBase=String(window.BOT_API_URL||window.location.origin).replace(/\/+$/,'');
  const initData=telegram&&telegram.initData;
  const canSave=!!(initData||(telegram&&typeof telegram.sendData==='function'));
  let dateTouched=false;
  function applySavedBirthday(birthday){
    if(!birthday||dateTouched)return;
    let year=DateCalendars.toCalendar('persian',today).year;
    while(year>1){
      try{
        const serial=DateCalendars.fromCalendar('persian',{year,month:birthday.month,day:birthday.day});
        if(serial<=today){
          const selected=DateCalendars.toCalendar(calendar.value,serial);
          setDate(selected);
          return;
        }
      }catch{}
      year--;
    }
  }
  window.addEventListener('birthday-state',event=>applySavedBirthday(event.detail&&event.detail.birthday));
  save.disabled=!canSave;
  if(canSave)saveHint.textContent='سال برای بررسی تاریخ استفاده می‌شه و فقط ماه و روز ذخیره می‌شن.';
  function todayParts(){return DateCalendars.toCalendar(calendar.value,today);}
  function setDate(date){
    dateParts={year:date.year,month:date.month,day:date.day};
    input.value=DateCalendars.formatDate(dateParts);
    $('year-trigger').textContent=numberFa.format(dateParts.year);
    $('month-trigger').textContent=monthNames[calendar.value][dateParts.month-1];
    $('day-trigger').textContent=numberFa.format(dateParts.day);
    render();
  }
  function validDays(year,month){
    const days=[];
    for(let day=1;day<=31;day++){
      try{DateCalendars.fromCalendar(calendar.value,{year,month,day});days.push(day);}catch{}
    }
    return days;
  }
  function closeMenus(){
    for(const id of ['calendar-options','year-options','month-options','day-options'])$(id).hidden=true;
    for(const id of ['calendar-trigger','year-trigger','month-trigger','day-trigger'])$(id).setAttribute('aria-expanded','false');
  }
  function fillOptions(menu,options,selected,kind){
    menu.replaceChildren();
    for(const option of options){
      const button=document.createElement('button');
      button.type='button';button.className=kind==='calendar'?'calendar-option':'date-option';
      button.setAttribute('role','option');button.setAttribute('aria-selected',String(option.value===selected));
      button.dataset.value=String(option.value);button.textContent=option.label;
      menu.append(button);
    }
    menu.hidden=false;
    const active=menu.querySelector('[aria-selected="true"]');
    if(active)menu.scrollTop=Math.max(0,active.offsetTop-(menu.clientHeight-active.offsetHeight)/2);
  }
  function openDateOptions(field){
    if(!$(field+'-options').hidden){closeMenus();return;}
    closeMenus();
    const range=DateCalendars.calendarRange(calendar.value);
    let options,selected;
    if(field==='year'){
      options=[];for(let year=range.minYear;year<=range.maxYear;year++)options.push({value:year,label:numberFa.format(year)});
      selected=dateParts.year;
    }else if(field==='month'){
      options=monthNames[calendar.value].map((label,index)=>({value:index+1,label}));selected=dateParts.month;
    }else{
      options=validDays(dateParts.year,dateParts.month).map(day=>({value:day,label:numberFa.format(day)}));selected=dateParts.day;
    }
    const menu=$(field+'-options'),trigger=$(field+'-trigger');
    fillOptions(menu,options,selected,'date');trigger.setAttribute('aria-expanded','true');
  }
  function chooseDateOption(field,option){
    const value=Number(option.dataset.value);
    const next={...dateParts,[field]:value};
    const days=validDays(next.year,next.month);
    if(!days.includes(next.day))next.day=Math.min(next.day,days[days.length-1]);
    dateTouched=true;closeMenus();setDate(next);
  }
  for(const field of ['year','month','day']){
    $(field+'-trigger').addEventListener('click',()=>openDateOptions(field));
    $(field+'-options').addEventListener('click',event=>{
      const option=event.target.closest('.date-option');
      if(option)chooseDateOption(field,option);
    });
  }
  $('calendar-trigger').addEventListener('click',()=>{
    if(!$('calendar-options').hidden){closeMenus();return;}
    closeMenus();const menu=$('calendar-options');
    fillOptions(menu,Object.entries(calendarNames).map(([value,label])=>({value,label})),calendar.value,'calendar');
    $('calendar-trigger').setAttribute('aria-expanded','true');
  });
  $('calendar-options').addEventListener('click',event=>{
    const option=event.target.closest('.calendar-option');if(!option)return;
    const old=DateCalendars.convert(calendar.value,input.value);
    calendar.value=option.dataset.value;
    $('calendar-current').textContent=calendarNames[calendar.value];
    $('calendar-options').querySelectorAll('.calendar-option').forEach(item=>item.setAttribute('aria-selected',String(item===option)));
    dateTouched=true;closeMenus();setDate(DateCalendars.toCalendar(calendar.value,old.serial));
  });
  document.addEventListener('click',event=>{if(!event.target.closest('.calendar-picker, .date-fields'))closeMenus();});
  document.addEventListener('keydown',event=>{if(event.key==='Escape')closeMenus();});
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
  $('today').addEventListener('click',()=>{dateTouched=true;closeMenus();setDate(todayParts());});
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
        save.textContent='ثبت تاریخ تولدم';
        save.disabled=false;
        window.dispatchEvent(new CustomEvent('birthday-saved'));
      }else{
        telegram.sendData(JSON.stringify({action:'save_birthday',calendar:'solar_hijri',year:p.year,month:p.month,day:p.day}));
        save.textContent='ثبت تاریخ تولدم';
      }
    }catch(error){saveHint.textContent=error.message||'ثبت انجام نشد. صفحه رو از داخل بات باز کن و دوباره تلاش کن.';save.disabled=false;}
  });
  setDate(todayParts());
  if(window.currentBirthday)applySavedBirthday(window.currentBirthday);
})();
