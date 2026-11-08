(() => {
  const panel = document.getElementById('timer-panel');
  if (!panel) return;
  const key = `studyreview:rest:v1:${document.body.dataset.userId}`;
  if (panel.dataset.session) {
    try { localStorage.removeItem(key); } catch (_) {}
    return;
  }
  const clock = document.getElementById('preview-clock');
  const caption = document.getElementById('preview-caption');
  const start = document.getElementById('start-rest');
  const end = document.getElementById('end-rest');
  const message = document.getElementById('rest-message');
  const form = document.querySelector('.focus-start');
  let deadline = 0;
  function read() {
    try { deadline = Number(localStorage.getItem(key)) || 0; } catch (_) {}
  }
  function stop(completed=false) {
    deadline=0;
    try { localStorage.removeItem(key); } catch (_) {}
    form.hidden=false; start.hidden=false; end.hidden=true;
    clock.textContent = `${String(form.querySelector('[name=minutes]:checked').value).padStart(2,'0')}:00`;
    caption.textContent='给专注一个开始';
    document.getElementById('timer-title').textContent='准备开始';
    message.textContent=completed?'休息结束了。准备好后，再点击开始专注。':'休息不计入专注；结束后由你决定何时开始下一轮。';
  }
  function tick() {
    if (!deadline) return;
    const remaining=Math.max(0,Math.ceil((deadline-Date.now())/1000));
    if (!remaining) { stop(true); return; }
    form.hidden=true; start.hidden=true; end.hidden=false;
    clock.textContent=`${String(Math.floor(remaining/60)).padStart(2,'0')}:${String(remaining%60).padStart(2,'0')}`;
    caption.textContent='休息中 · 不计入专注';
    document.getElementById('timer-title').textContent='休息中';
  }
  start.addEventListener('click', () => {
    deadline=Date.now()+300000;
    try { localStorage.setItem(key,String(deadline)); message.textContent='起身走走，看看远处。刷新页面也可恢复这段休息。'; }
    catch (_) { message.textContent='浏览器未允许保存休息状态；关闭页面后本次休息提醒不会保留。'; }
    tick();end.focus();
  });
  end.addEventListener('click', () => {stop();(form.querySelector('select:not(:disabled)') || form.querySelector('[name=minutes]:checked')).focus();});
  window.addEventListener('storage',event=>{if(event.key===key){read();if(deadline)tick();else stop();}});
  document.addEventListener('visibilitychange',()=>{if(!document.hidden)tick();});
  read();tick();setInterval(tick,1000);
})();
