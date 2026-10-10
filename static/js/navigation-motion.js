'use strict';
// Original progressive enhancement for Django's ordinary multi-page navigation.
// No fetch routing, prevented clicks, history mutation, scroll or focus changes.
(() => {
  const key = 'study-review.navigation.v1';
  const reduced = window.matchMedia('(prefers-reduced-motion: reduce)');
  const duration = 210;
  const stagger = 18;
  let submitting = false;
  let nativeHandled = false;
  let nativeTransition = null;
  let generation = 0;
  let animations = [];

  function forget() {
    try { sessionStorage.removeItem(key); } catch { /* Storage is optional. */ }
  }
  function marker() {
    try {
      const value = JSON.parse(sessionStorage.getItem(key));
      return value && Date.now() - value.created < 10000 ? value : null;
    } catch { return null; }
  }
  function path(url) {
    try {
      const parsed = new URL(url, location.href);
      return parsed.origin === location.origin ? parsed.pathname : null;
    } catch { return null; }
  }
  function columnPage(url) {
    const pathname = path(url);
    return pathname && [...document.querySelectorAll('.sidebar .nav-link')]
      .some(link => path(link.href) === pathname);
  }
  function column(url) {
    const pathname = path(url);
    if (!pathname) return null;
    const link = [...document.querySelectorAll('.sidebar .nav-link')].find(item => {
      const base = path(item.href);
      return pathname === base || (base !== '/' && pathname.startsWith(base));
    });
    return link ? path(link.href) : null;
  }
  function eligible(from, to, type) {
    if (submitting || reduced.matches || !column(from) || !columnPage(to) || column(from) === column(to)) return false;
    if (type === 'traverse') return true;
    const pending = marker();
    return Boolean(pending && pending.from === path(from) && pending.to === path(to));
  }
  function blocks() {
    const main = document.querySelector('.main-content');
    if (!main) return [];
    const result = [];
    for (const child of main.children) {
      if (child.matches('.page-footer, .back-link, script')) continue;
      const items = child.matches('.page-heading, .metric-grid, .two-columns, .course-grid, .question-list, .review-layout')
        ? [...child.children] : [child];
      for (const item of items) {
        const rect = item.getBoundingClientRect();
        if (rect.width && rect.height && rect.bottom > 0 && rect.top < innerHeight + 80) result.push(item);
      }
    }
    return result.slice(0, 12);
  }
  function prepare() {
    const current = ++generation;
    const items = blocks();
    items.forEach((item, index) => { item.style.viewTransitionName = `study-block-${index + 1}`; });
    return () => {
      if (current !== generation) return;
      items.forEach(item => { item.style.removeProperty('view-transition-name'); });
    };
  }
  function cancelAnimations() {
    animations.forEach(animation => animation.cancel());
    animations = [];
  }
  function fallback() {
    const pending = marker();
    if (!pending || !eligible(pending.from, location.href, 'push')) return;
    forget();
    cancelAnimations();
    for (const [index, item] of blocks().entries()) {
      if (typeof item.animate !== 'function') continue;
      const animation = item.animate([
        {clipPath: 'inset(0 0 100% 0)', transform: 'translateY(8px)'},
        {clipPath: 'inset(0)', transform: 'translateY(0)'}
      ], {duration, delay: index % 6 * stagger, easing: 'cubic-bezier(.16, 1, .3, 1)', fill: 'backwards'});
      animations.push(animation);
      animation.finished.catch(() => {});
    }
    // Base content is never hidden. Even an interrupted script ends at visible content.
  }

  document.addEventListener('click', event => {
    const link = event.target.closest?.('.sidebar .nav-link');
    if (!link || event.defaultPrevented || event.button !== 0 || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey
      || link.download || (link.target && link.target !== '_self')) return;
    if (!eligible(location.href, link.href, 'traverse')) { forget(); return; }
    try {
      sessionStorage.setItem(key, JSON.stringify({from: location.pathname, to: path(link.href), created: Date.now()}));
    } catch { /* Normal navigation remains available. */ }
  });
  document.addEventListener('submit', () => {
    submitting = true;
    forget();
    cancelAnimations();
  }, true);

  window.addEventListener('pageswap', event => {
    if (!event.viewTransition) return;
    try {
      const destination = event.activation?.entry?.url;
      if (!eligible(location.href, destination, event.activation?.navigationType)) {
        event.viewTransition.skipTransition();
        return;
      }
      const cleanup = prepare();
      event.viewTransition.finished.then(cleanup, cleanup);
    } catch { event.viewTransition.skipTransition(); }
  });
  window.addEventListener('pagereveal', event => {
    if (!event.viewTransition) return;
    try {
      const activation = window.navigation?.activation;
      if (!eligible(activation?.from?.url, location.href, activation?.navigationType)) {
        event.viewTransition.skipTransition();
        return;
      }
      nativeHandled = true;
      forget();
      const cleanup = prepare();
      nativeTransition = event.viewTransition;
      event.viewTransition.ready.catch(() => {});
      event.viewTransition.finished.then(() => {
        cleanup();
        nativeTransition = null;
      }, () => { cleanup(); nativeTransition = null; });
    } catch { event.viewTransition.skipTransition(); }
  });
  window.addEventListener('pageshow', () => {
    submitting = false;
    nativeHandled = false;
    const enter = () => {
      if (!nativeHandled) {
        try { fallback(); } catch { cancelAnimations(); forget(); }
      }
    };
    // Chromium fires pageshow before pagereveal. Give the native event its
    // snapshot opportunity before considering a fallback on that browser.
    if ('onpagereveal' in window) requestAnimationFrame(() => requestAnimationFrame(enter));
    else enter();
  });
  reduced.addEventListener?.('change', () => {
    if (!reduced.matches) return;
    cancelAnimations();
    nativeTransition?.skipTransition();
    forget();
  });
})();
