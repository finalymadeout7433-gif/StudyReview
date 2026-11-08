const {test}=require('node:test');
const assert=require('node:assert/strict');
const fs=require('node:fs');
const vm=require('node:vm');

const source=fs.readFileSync(require.resolve('../../static/js/pixel-studio.js'),'utf8');
const storageKey=user=>`studyreview:pixel-motion:v2:${user||'guest'}`;
const labels={running:'动态：开',off:'动态：关',hidden:'动态：暂停',offscreen:'动态：暂停',reduced:'已减少动态'};
const titles={normal:'只控制装饰动画，不影响专注计时',paused:'画面不可见时暂停，回来后自动继续',reduced:'遵循系统减少动态设置'};

function eventTarget(target={}){
  const listeners=new Map();
  target.addEventListener=(type,listener)=>{
    if(!listeners.has(type))listeners.set(type,[]);
    listeners.get(type).push(listener);
  };
  target.emit=(type,event={})=>{for(const listener of listeners.get(type)||[])listener(event);};
  return target;
}

function makeScene(dataset={},actions=['motion','wind','light']){
  const buttons=actions.map(action=>({
    dataset:{action},hidden:true,disabled:false,textContent:'',title:'',attributes:{},
    setAttribute(name,value){this.attributes[name]=String(value);},
    closest(selector){assert.equal(selector,'button[data-action]');return this;}
  }));
  return eventTarget({
    dataset:{scene:'',wind:'on',light:'on',...dataset},buttons,
    contains:button=>buttons.includes(button),
    querySelectorAll(selector){
      const actions=[...selector.matchAll(/\[data-action=(?:"([^"]+)"|([^\]]+))\]/g)].map(match=>match[1]||match[2]);
      assert.ok(actions.length,`Unexpected scene selector: ${selector}`);
      return buttons.filter(button=>actions.includes(button.dataset.action));
    }
  });
}

// Only the controller contract is stubbed. CSS phase continuity is checked in
// the real-browser test, not inferred from these data attributes.
function boot({userId='test-user',stored,storage=new Map(),storageThrows=false,storageMissing=false,
  reduced=false,hidden=false,intersection=true,legacyMedia=false,scenes=[makeScene({focusScene:'',mode:'ready'})]}={}){
  const key=storageKey(userId),writes=[],reads=[],observed=[];
  if(stored!==undefined)storage.set(key,stored);
  const timer=Object.freeze({dataset:Object.freeze({status:'ready',session:'',remaining:'1500'})});
  const document=eventTarget({
    body:{dataset:{section:'focus',userId}},hidden,
    querySelector(selector){
      if(selector==='#timer-panel')return timer;
      if(['.page-heading h1','.valley-banner','.page-heading'].includes(selector))return null;
      throw Error(`Unexpected document selector: ${selector}`);
    },
    getElementById:id=>id==='timer-panel'?timer:null,
    querySelectorAll(selector){assert.equal(selector,'[data-scene]');return scenes;}
  });
  const window=eventTarget(),media=eventTarget({matches:reduced});
  if(legacyMedia){
    media.addListener=listener=>eventTarget.prototype; // Replaced below with the legacy change registration.
    const add=media.addEventListener;
    media.addListener=listener=>add('change',listener);
    delete media.addEventListener;
  }
  let intersect;
  class IntersectionObserver{
    constructor(callback){intersect=callback;}
    observe(scene){observed.push(scene);}
  }
  if(intersection)window.IntersectionObserver=IntersectionObserver;
  const localStorage={
    getItem(name){reads.push(name);if(storageThrows)throw Error('Storage denied');return storage.get(name)??null;},
    setItem(name,value){if(storageThrows)throw Error('Storage denied');writes.push([name,value]);storage.set(name,value);}
  };
  const context={document,window,IntersectionObserver,
    matchMedia(query){assert.equal(query,'(prefers-reduced-motion: reduce)');return media;},
    fetch(){assert.fail('Scenery must not make business requests');},
    setInterval(){assert.fail('Scenery must not start a timer');}
  };
  if(!storageMissing)context.localStorage=localStorage;
  vm.runInNewContext(source,context,{filename:'pixel-studio.js'});
  return {document,window,media,scenes,storage,key,writes,reads,observed,timer,
    click(action,scene=scenes[0]){
      const button=scene.buttons.find(button=>button.dataset.action===action);
      assert.ok(button,`Missing ${action} button`);
      // Native disabled buttons cannot dispatch a user click.
      if(!button.disabled)scene.emit('click',{target:button});
    },
    visibility(value){document.hidden=value;document.emit('visibilitychange');},
    reducedMotion(value){media.matches=value;media.emit('change',{matches:value});},
    intersection(entries){assert.ok(intersect,'IntersectionObserver is not installed');intersect(entries);},
    storageEvent(name,value){window.emit('storage',{key:name,newValue:value});}
  };
}

function assertState(scene,state,{enabled=true}={}){
  assert.equal(scene.dataset.motionState,state);
  assert.equal(scene.dataset.animate,String(state==='running'));
  for(const button of scene.buttons){
    assert.equal(button.hidden,false);
    if(button.dataset.action!=='motion')continue;
    assert.equal(button.disabled,state==='reduced');
    assert.equal(button.attributes['aria-pressed'],String(enabled&&state!=='reduced'));
    assert.equal(button.textContent,labels[state]);
    assert.equal(button.title,state==='reduced'?titles.reduced:['hidden','offscreen'].includes(state)?titles.paused:titles.normal);
  }
}

test('ambient scenery runs in ready, running, paused, rest and finished timer modes',()=>{
  for(const mode of ['ready','running','paused','rest','finished']){
    const scenes=[makeScene({focusScene:'',mode}),makeScene(),makeScene({},[])];
    const app=boot({scenes});
    scenes.forEach(scene=>assertState(scene,'running'));
    assert.deepEqual(app.observed,scenes);
    assert.equal(scenes[0].dataset.mode,mode);
    assert.deepEqual(app.timer.dataset,{status:'ready',session:'',remaining:'1500'});
    assert.deepEqual(app.writes,[]);
    assert.deepEqual(app.reads,[app.key]);
  }
});

test('saved off preference applies to every scene and survives reload',()=>{
  const app=boot({stored:'off',scenes:[makeScene(),makeScene(),makeScene({},[])]});
  app.scenes.forEach(scene=>assertState(scene,'off',{enabled:false}));
  assert.deepEqual(app.writes,[]);
  app.click('motion');
  app.scenes.forEach(scene=>assertState(scene,'running'));
  assert.deepEqual(app.writes,[[app.key,'on']]);
  app.click('motion',app.scenes[1]);
  assert.deepEqual(app.writes,[[app.key,'on'],[app.key,'off']]);
  const reloaded=boot({storage:app.storage});
  assertState(reloaded.scenes[0],'off',{enabled:false});
});

test('reduced motion disables motion buttons without overwriting the saved preference',()=>{
  for(const stored of ['on','off']){
    const app=boot({stored,reduced:true}),scene=app.scenes[0],enabled=stored==='on';
    assertState(scene,'reduced',{enabled});
    app.click('motion');
    assert.equal(app.storage.get(app.key),stored);
    app.reducedMotion(false);
    assertState(scene,enabled?'running':'off',{enabled});
    app.reducedMotion(true);
    assertState(scene,'reduced',{enabled});
    assert.deepEqual(app.writes,[]);
  }
});

test('hidden and offscreen scenes pause independently and resume only when both gates reopen',()=>{
  const app=boot({scenes:[makeScene(),makeScene()]}),[room,banner]=app.scenes;
  app.intersection([{target:room,isIntersecting:false},{target:banner,isIntersecting:true}]);
  assertState(room,'offscreen');assertState(banner,'running');
  app.visibility(true);
  app.scenes.forEach(scene=>assertState(scene,'hidden'));
  app.visibility(false);
  assertState(room,'offscreen');assertState(banner,'running');
  app.visibility(true);
  app.intersection([{target:room,isIntersecting:true}]);
  assertState(room,'hidden');
  app.visibility(false);
  app.scenes.forEach(scene=>assertState(scene,'running'));
  assert.deepEqual(app.writes,[]);
});

test('pageshow recalculates visibility when returning to a restored page',()=>{
  const app=boot({hidden:true});
  assertState(app.scenes[0],'hidden');
  app.document.hidden=false;
  app.window.emit('pageshow',{persisted:true});
  assertState(app.scenes[0],'running');
  app.click('motion');
  app.window.emit('pageshow',{persisted:true});
  assertState(app.scenes[0],'off',{enabled:false});
});

test('explicit off and reduced motion retain precedence over visibility gates',()=>{
  const app=boot({stored:'off',hidden:true}),scene=app.scenes[0];
  app.intersection([{target:scene,isIntersecting:false}]);
  assertState(scene,'off',{enabled:false});
  app.reducedMotion(true);assertState(scene,'reduced',{enabled:false});
  app.reducedMotion(false);assertState(scene,'off',{enabled:false});
  app.visibility(false);app.intersection([{target:scene,isIntersecting:true}]);
  assertState(scene,'off',{enabled:false});
});

test('wind and light controls are local and independent of global motion',()=>{
  const app=boot({scenes:[makeScene(),makeScene()]}),[room,banner]=app.scenes;
  const button=action=>room.buttons.find(button=>button.dataset.action===action);
  assert.equal(button('wind').textContent,'风车：转');
  assert.equal(button('light').textContent,'灯塔：亮');
  app.click('wind');
  assert.equal(room.dataset.wind,'off');assert.equal(room.dataset.light,'on');
  assert.equal(button('wind').attributes['aria-pressed'],'false');
  assert.equal(button('wind').textContent,'风车：停');
  assertState(room,'running');
  app.click('light');
  assert.equal(room.dataset.light,'off');
  assert.equal(button('light').attributes['aria-pressed'],'false');
  assert.equal(button('light').textContent,'灯塔：灭');
  assert.equal(banner.dataset.wind,'on');assert.equal(banner.dataset.light,'on');
  assert.deepEqual(app.writes,[]);
  app.click('motion');
  app.scenes.forEach(scene=>assertState(scene,'off',{enabled:false}));
  app.click('wind');app.click('light');
  assert.equal(room.dataset.wind,'on');assert.equal(room.dataset.light,'on');
  assertState(room,'off',{enabled:false});
  app.click('motion');
  app.scenes.forEach(scene=>assertState(scene,'running'));
  assert.equal(button('wind').attributes['aria-pressed'],'true');
  assert.equal(button('light').attributes['aria-pressed'],'true');
  assert.deepEqual(app.writes,[[app.key,'off'],[app.key,'on']]);
});

test('storage events sync only the current user and preserve local scene controls',()=>{
  const app=boot({scenes:[makeScene(),makeScene()]}),scene=app.scenes[0];
  app.click('wind');
  app.storageEvent(storageKey('another-user'),'off');
  app.scenes.forEach(scene=>assertState(scene,'running'));
  app.storageEvent(app.key,'off');
  app.scenes.forEach(scene=>assertState(scene,'off',{enabled:false}));
  app.storageEvent(app.key,'on');
  app.scenes.forEach(scene=>assertState(scene,'running'));
  app.storageEvent(app.key,'off');app.storageEvent(app.key,null);
  app.scenes.forEach(scene=>assertState(scene,'running'));
  assert.equal(scene.dataset.wind,'off');
  assert.deepEqual(app.writes,[]);
});

test('storage sync cannot bypass reduced motion, hidden or offscreen gates',()=>{
  const app=boot({stored:'off',reduced:true,hidden:true}),scene=app.scenes[0];
  app.intersection([{target:scene,isIntersecting:false}]);
  app.storageEvent(app.key,'on');assertState(scene,'reduced');
  app.reducedMotion(false);assertState(scene,'hidden');
  app.visibility(false);assertState(scene,'offscreen');
  app.intersection([{target:scene,isIntersecting:true}]);assertState(scene,'running');
  assert.deepEqual(app.writes,[]);
});

test('guest preference has its own storage key',()=>{
  const app=boot({userId:undefined,stored:'off'});
  // Empty user IDs represent the template's unauthenticated/guest fallback.
  const guest=boot({userId:'',stored:'off'});
  assert.equal(guest.key,'studyreview:pixel-motion:v2:guest');
  assert.deepEqual(guest.reads,[guest.key]);
  assertState(guest.scenes[0],'off',{enabled:false});
  guest.click('motion');assert.deepEqual(guest.writes,[[guest.key,'on']]);
  assert.notEqual(app.key,guest.key);
});

test('unavailable storage falls back to live in-memory controls without throwing',()=>{
  for(const options of [{storageThrows:true},{storageMissing:true}]){
    const app=boot(options),scene=app.scenes[0];
    assertState(scene,'running');
    app.click('motion');assertState(scene,'off',{enabled:false});
    app.visibility(true);app.visibility(false);
    assertState(scene,'off',{enabled:false});
    app.click('motion');assertState(scene,'running');
    assert.deepEqual(app.writes,[]);
  }
});

test('missing IntersectionObserver still supports visibility and motion controls',()=>{
  const app=boot({intersection:false}),scene=app.scenes[0];
  assertState(scene,'running');assert.deepEqual(app.observed,[]);
  app.visibility(true);assertState(scene,'hidden');
  app.visibility(false);assertState(scene,'running');
  app.click('motion');assertState(scene,'off',{enabled:false});
});

test('legacy media-query listeners still update reduced-motion state',()=>{
  const app=boot({legacyMedia:true}),scene=app.scenes[0];
  app.reducedMotion(true);assertState(scene,'reduced');
  app.reducedMotion(false);assertState(scene,'running');
});

test('delegated scene clicks ignore non-controls and controls outside the scene',()=>{
  const app=boot(),scene=app.scenes[0];
  scene.emit('click',{target:{closest:()=>null}});
  scene.emit('click',{target:makeScene().buttons[0]});
  assertState(scene,'running');assert.deepEqual(app.writes,[]);
  const button=scene.buttons[0];
  scene.emit('click',{target:{closest:()=>button}});
  assertState(scene,'off',{enabled:false});
});
