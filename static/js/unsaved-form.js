'use strict';
// Warn about unsaved learning forms without storing their private contents elsewhere.
document.querySelectorAll('form[data-entry-form]').forEach(form => {
  const status = form.querySelector('[data-unsaved-status]');
  const snapshot = () => JSON.stringify([...new FormData(form)].filter(([key]) => !['csrfmiddlewaretoken', 'token'].includes(key)));
  const initial = snapshot();
  let submitting = false;
  const dirty = () => form.dataset.boundErrors === 'true' || snapshot() !== initial || Boolean(form.querySelector('[data-image-editor]')?.imageEditor?.pending);
  const update = () => { if (status) status.textContent = dirty() ? '更改尚未保存，请点击保存后再离开。' : ''; };
  ['input', 'change', 'imageschanged'].forEach(name => form.addEventListener(name, update));
  form.addEventListener('submit', event => {
    if (!event.defaultPrevented && form.checkValidity()) submitting = true;
  });
  window.addEventListener('beforeunload', event => {
    if (!submitting && dirty()) { event.preventDefault(); event.returnValue = ''; }
  });
  window.addEventListener('pageshow', () => { submitting = false; update(); });
  update();
});
