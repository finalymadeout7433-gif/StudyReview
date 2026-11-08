/* Decorative state observer. Never submits forms, changes clocks, or requests server state. */
(() => {
  'use strict';
  const room = document.querySelector('[data-focus-scene]');
  const panel = document.getElementById('timer-panel');
  const actor = room && room.querySelector('.focus-scholar');
  if (!actor || !panel) return;
  const user = document.body.dataset.userId || 'guest';
  const storageKey = 'studyreview:scholar:v1:' + user;
  const motionKey = 'studyreview:pixel-motion:v2:' + user;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let timer = null, visible = true, mode = '', phase = 0, lastSession = '', finished = false;
  try {
    const saved = JSON.parse(sessionStorage.getItem(storageKey) || '{}');
    lastSession = saved.session || '';
    finished = saved.ending === true && Date.now() - saved.at < 60000;
  } catch (_) {}
  const newSession = !!panel.dataset.session && panel.dataset.session !== lastSession;
  // Carry only visual continuity across normal POST redirects. Failed posts keep server status authoritative.
  try { sessionStorage.setItem(storageKey, JSON.stringify({session:panel.dataset.session || '', at:Date.now()})); } catch (_) {}
  document.addEventListener('submit', event => {
    if (event.target.id !== 'focus-controls') return;
    const action = event.submitter && event.submitter.value;
    if (action !== 'finish' && action !== 'complete') return;
    try { sessionStorage.setItem(storageKey, JSON.stringify({session:panel.dataset.session, ending:true, at:Date.now()})); } catch (_) {}
  });
  function allowed() {
    let enabled = true;
    try { enabled = localStorage.getItem(motionKey) !== 'off'; } catch (_) {}
    return enabled && !reduced.matches && !document.hidden && visible;
  }
  function currentMode() {
    if (panel.dataset.status === 'running') return 'study';
    if (panel.dataset.status === 'paused') return 'rest';
    const endRest = document.getElementById('end-rest');
    return finished || (endRest && !endRest.hidden) ? 'rest' : 'idle';
  }
  function pose(name) { actor.dataset.character = name; }
  function advance() {
    clearTimeout(timer);
    if (!allowed()) return;
    const study = [['reading',9000],['writing',11000],['reading',7000],['writing',10000]];
    const rest = [['drinking',4000],['stretching',4000],['walking',8000],['drinking',5000]];
    const cycle = mode === 'study' ? study : rest;
    const [name, delay] = cycle[phase++ % cycle.length];
    pose(name);
    timer = setTimeout(advance,delay);
  }
  let entered = !newSession;
  function update() {
    const next = currentMode(), changed = next !== mode;
    const animate = allowed();
    room.dataset.characterMotion = animate ? 'on' : 'off';
    if (changed) { mode = next; phase = 0; clearTimeout(timer); timer = null; }
    if (!animate || mode === 'idle') {
      clearTimeout(timer); timer = null;
      pose(mode === 'study' ? 'reading' : mode === 'rest' ? 'drinking' : 'idle');
      return;
    }
    if (!changed && timer !== null) return;
    if (mode === 'study' && !entered) {
      entered = true; pose('entering'); timer = setTimeout(advance,2400);
    } else advance();
  }
  const observer = new MutationObserver(update);
  observer.observe(panel,{attributes:true,attributeFilter:['data-status','data-session']});
  const endRest = document.getElementById('end-rest');
  if (endRest) observer.observe(endRest,{attributes:true,attributeFilter:['hidden']});
  room.addEventListener('click',event => {
    if (event.target.closest('[data-action="motion"]')) update();
  });
  const endButton = document.getElementById('end-rest');
  if (endButton) endButton.addEventListener('click',() => { finished = false; update(); });
  document.addEventListener('visibilitychange',update);
  window.addEventListener('storage',event => { if (event.key === motionKey) update(); });
  window.addEventListener('pageshow',update);
  window.addEventListener('pagehide',() => { clearTimeout(timer); timer = null; });
  if (reduced.addEventListener) reduced.addEventListener('change',update);
  else reduced.addListener(update);
  if ('IntersectionObserver' in window) new IntersectionObserver(entries => {
    visible = entries[0].isIntersecting; update();
  }).observe(room);
  update();
})();
