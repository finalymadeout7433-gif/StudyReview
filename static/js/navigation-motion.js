'use strict';
// Keep Django navigation immediate: no fetch routing, interception or snapshots.
(() => {
  const key = 'study-review.navigation.v1';
  const reduced = matchMedia('(prefers-reduced-motion: reduce)');
  let animation;
  const clear = () => { try { sessionStorage.removeItem(key); } catch {} };
  document.addEventListener('click', event => {
    const link = event.target.closest?.('.sidebar .nav-link');
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey || link.hasAttribute('download') || (link.target && link.target !== '_self')) return;
    const url = new URL(link.href, location.href);
    if (reduced.matches || url.origin !== location.origin || url.pathname === location.pathname) { clear(); return; }
    link.classList.add('navigation-pending');
    try { sessionStorage.setItem(key, JSON.stringify({to: url.pathname, created: Date.now()})); } catch {}
    setTimeout(() => link.classList.remove('navigation-pending'), 1800);
  });
  // Also disable snapshots if an older cached stylesheet still opts into them.
  for (const name of ['pageswap', 'pagereveal']) {
    window.addEventListener(name, event => event.viewTransition?.skipTransition());
  }
  const enter = () => {
    let pending;
    try { pending = JSON.parse(sessionStorage.getItem(key)); } catch {}
    clear();
    if (reduced.matches || !pending || pending.to !== location.pathname || Date.now() - pending.created > 10000) return;
    const main = document.querySelector('.main-content');
    if (!main?.animate) return;
    // One compositor-friendly layer, no geometry reads, clipping or stagger.
    animation = main.animate([
      {opacity: .88, transform: 'translateY(4px)'},
      {opacity: 1, transform: 'translateY(0)'}
    ], {duration: 120, easing: 'ease-out'});
    animation.finished.catch(() => {});
  };
  if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', enter, {once: true});
  else enter();
  document.addEventListener('submit', () => { clear(); animation?.cancel(); }, true);
  window.addEventListener('pagehide', () => animation?.cancel());
  window.addEventListener('pageshow', event => { document.querySelectorAll('.navigation-pending').forEach(link => link.classList.remove('navigation-pending')); if (event.persisted) clear(); });
  reduced.addEventListener?.('change', () => { if (reduced.matches) { clear(); animation?.cancel(); } });
})();

