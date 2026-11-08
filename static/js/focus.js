(() => {
  const panel = document.getElementById('timer-panel');
  const clock = document.getElementById('focus-clock');
  const message = document.getElementById('timer-message');
  const format = seconds => `${String(Math.floor(seconds / 60)).padStart(2,'0')}:${String(seconds % 60).padStart(2,'0')}`;
  document.querySelectorAll('input[name="minutes"]').forEach(input => input.addEventListener('change', () => {
    document.getElementById('preview-clock').textContent = format(Number(input.value)*60);
  }));
  let initial = clock ? Number(clock.dataset.seconds) : 0;
  let anchor = performance.now();
  let submitted = false, syncing = false;
  async function sync() {
    if (!panel || syncing || submitted) return;
    syncing = true;
    try {
      const response = await fetch(panel.dataset.stateUrl, {cache:'no-store', signal:AbortSignal.timeout(8000)});
      if (!response.ok || response.redirected) throw new Error('Unavailable');
      const data = await response.json();
      if (String(data.session || '') !== panel.dataset.session || (data.status || '') !== panel.dataset.status) {
        window.location.reload(); return;
      }
      initial = data.remaining; anchor = performance.now();
      const today = document.getElementById('today-focus-minutes');
      if (today) today.textContent = data.today_minutes;
      if (data.week) {
        const peak=Math.max(1,...data.week.map(row=>row.seconds));
        document.querySelectorAll('.week-bars li').forEach((li,index)=>{
          const row=data.week[index];
          li.querySelector('.week-day').textContent=row.day.slice(5);
          li.querySelector('.week-fill').style.width=`${row.seconds/peak*100}%`;
          li.querySelector('.week-value').textContent=row.label;
          li.title=`${row.day}：${row.seconds} 秒`;
        });
        const total=document.getElementById('week-total');
        if(total) total.textContent=data.week_minutes;
        const days=document.getElementById('week-days');
        if(days) days.textContent=data.week_active_days;
        const empty=document.getElementById('week-empty');if(empty) empty.hidden=data.week_active_days>0;
      }
      if (message) message.textContent = panel.dataset.status === 'paused' ? '已暂停，休息时间不会计入专注。' : '计时已同步，可放心继续。';
      if (clock && data.status === 'running' && data.remaining === 0) {
        submitted = true;
        message.textContent = '本轮已到时，正在保存记录。';
        document.getElementById('focus-controls').requestSubmit(document.getElementById('complete-focus'));
      }
    } catch (_) {
      if (message) message.textContent = '暂时无法同步。计时记录仍在服务器，连接恢复后会重试；刷新也可恢复。';
    } finally { syncing = false; }
  }
  function tick() {
    if (!clock) return;
    const remaining = Math.max(0, initial - (clock.dataset.running === 'true' ? Math.floor((performance.now()-anchor)/1000) : 0));
    clock.textContent = format(remaining);
    if (!remaining && clock.dataset.running === 'true') sync();
  }
  tick(); setInterval(tick, 1000);
  // Server state wins after tab suspension, offline periods and other tabs.
  setInterval(sync,15000);
  document.addEventListener('visibilitychange', () => { if (!document.hidden) sync(); });
  window.addEventListener('pageshow', event => { if (event.persisted) sync(); });
  window.addEventListener('online',sync);
})();
