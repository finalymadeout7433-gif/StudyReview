/* Only scenery and display preferences. No timer writes, requests or business state. */
(() => {
 'use strict';
 const section=document.body.dataset.section;
 const heading=document.querySelector('.page-heading h1');
 if(heading && document.getElementById('pixel-'+section)){
  const ns='http://www.w3.org/2000/svg',tile=document.createElement('span'),svg=document.createElementNS(ns,'svg'),use=document.createElementNS(ns,'use');
  tile.className='pixel-heading-icon';tile.setAttribute('aria-hidden','true');svg.classList.add('pixel-icon');svg.setAttribute('viewBox','0 0 16 16');svg.setAttribute('focusable','false');use.setAttribute('href','#pixel-'+section);svg.append(use);tile.append(svg);heading.prepend(tile);
 }
 const banner=document.querySelector('.valley-banner'),pageHeading=document.querySelector('.page-heading');
 if(banner && pageHeading)pageHeading.after(banner);
 const scenes=[...document.querySelectorAll('[data-scene]')];
 const media=matchMedia('(prefers-reduced-motion: reduce)');
 const key='studyreview:pixel-motion:v2:'+(document.body.dataset.userId||'guest');
 let enabled=true;
 try{enabled=localStorage.getItem(key)!=='off'}catch(_){}
 const visible=new WeakMap(scenes.map(s=>[s,true]));
 function update(){
  scenes.forEach(scene=>{
   // Ambient scenery is independent of study/timer state, including the ready room.
   const state=media.matches?'reduced':!enabled?'off':document.hidden?'hidden':!visible.get(scene)?'offscreen':'running';
   scene.dataset.animate=String(state==='running');
   scene.dataset.motionState=state;
   scene.querySelectorAll('[data-action=wind],[data-action=light]').forEach(b=>b.hidden=false);
   scene.querySelectorAll('[data-action="motion"]').forEach(b=>{
    b.hidden=false;b.disabled=media.matches;b.setAttribute('aria-pressed',String(enabled&&!media.matches));
    b.textContent=media.matches?'已减少动态':!enabled?'动态：关':state==='running'?'动态：开':'动态：暂停';
    b.title=media.matches?'遵循系统减少动态设置':state==='hidden'||state==='offscreen'?'画面不可见时暂停，回来后自动继续':'只控制装饰动画，不影响专注计时';
   });
   scene.querySelectorAll('[data-action="wind"]').forEach(b=>{b.setAttribute('aria-pressed',String(scene.dataset.wind!=='off'));b.textContent=scene.dataset.wind==='off'?'风车：停':'风车：转'});
   scene.querySelectorAll('[data-action="light"]').forEach(b=>{b.setAttribute('aria-pressed',String(scene.dataset.light!=='off'));b.textContent=scene.dataset.light==='off'?'灯塔：灭':'灯塔：亮'});
  });
 }
 scenes.forEach(scene=>scene.addEventListener('click',e=>{
  const button=e.target.closest('button[data-action]');if(!button||!scene.contains(button))return;
  const action=button.dataset.action;
  if(action==='motion'){enabled=!enabled;try{localStorage.setItem(key,enabled?'on':'off')}catch(_){}}
  else if(action==='wind'){scene.dataset.wind=scene.dataset.wind==='off'?'on':'off'}
  else if(action==='light'){scene.dataset.light=scene.dataset.light==='off'?'on':'off'}
  update();
 }));
 if('IntersectionObserver' in window){
  const observer=new IntersectionObserver(entries=>{entries.forEach(e=>visible.set(e.target,e.isIntersecting));update()});
  scenes.forEach(s=>observer.observe(s));
 }
 document.addEventListener('visibilitychange',update);window.addEventListener('pageshow',update);
 window.addEventListener('storage',e=>{if(e.key===key){enabled=e.newValue!=='off';update()}});
 if(media.addEventListener)media.addEventListener('change',update);else media.addListener(update);
 update();
})();
