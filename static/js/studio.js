'use strict';
// Small, local enhancements. All essential forms still work without JavaScript.
(() => {
  document.querySelectorAll('.auth-card input[type="password"]').forEach(input => {
    const wrapper = document.createElement('div'); wrapper.className = 'password-wrap';
    input.before(wrapper); wrapper.append(input);
    const toggle = document.createElement('button'); toggle.type = 'button';
    toggle.className = 'password-toggle'; toggle.textContent = '显示';
    toggle.setAttribute('aria-label', '显示密码'); toggle.setAttribute('aria-pressed', 'false');
    toggle.addEventListener('click', () => {
      const visible = input.type === 'password'; input.type = visible ? 'text' : 'password';
      toggle.textContent = visible ? '隐藏' : '显示';
      toggle.setAttribute('aria-label', visible ? '隐藏密码' : '显示密码');
      toggle.setAttribute('aria-pressed', String(visible));
    }); wrapper.append(toggle);
  });
  document.addEventListener('click', event => {
    if (event.target.closest('[data-mi-target]')) {
      const menu = event.target.closest('.row-menu'); if (menu) menu.open = false;
    }
    document.querySelectorAll('.row-menu[open]').forEach(menu => {
      if (!menu.contains(event.target)) menu.open = false;
    });
  });
  document.addEventListener('keydown', event => {
    if (event.key === 'Escape') document.querySelectorAll('.row-menu[open]').forEach(menu => { menu.open = false; });
  });
})();
