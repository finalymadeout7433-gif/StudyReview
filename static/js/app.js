'use strict';
// Small progressive enhancements. Forms and review work without JavaScript.
document.querySelectorAll('form').forEach(form => {
  form.addEventListener('submit', event => {
    if (event.defaultPrevented || !form.checkValidity()) return;
    form.querySelectorAll('[data-save]').forEach(button => {
      button.disabled = true;
      button.textContent = '正在保存…';
    });
  });
});
window.addEventListener('pageshow', () => {
  document.querySelectorAll('[data-save]').forEach(button => {
    button.disabled = false;
    if (button.dataset.originalText) button.textContent = button.dataset.originalText;
  });
});
document.querySelectorAll('[data-save]').forEach(button => { button.dataset.originalText = button.textContent; });

const questionForm = document.querySelector('[data-question-form]');
if (questionForm) {
  const courseSelect = questionForm.querySelector('[name="course"]');
  const points = questionForm.querySelector('#id_knowledge_points');
  let requestNumber = 0;
  if (courseSelect && points && !courseSelect.disabled) {
    courseSelect.addEventListener('change', async () => {
      const thisRequest = ++requestNumber;
      points.replaceChildren();
      if (!courseSelect.value) return;
      try {
        const response = await fetch(`/courses/${encodeURIComponent(courseSelect.value)}/points.json`, {credentials: 'same-origin'});
        if (!response.ok) throw new Error('Unable to load points');
        const data = await response.json();
        if (thisRequest !== requestNumber) return;
        for (const point of data.points) {
          const wrapper = document.createElement('div');
          const label = document.createElement('label');
          const checkbox = document.createElement('input');
          checkbox.type = 'checkbox'; checkbox.name = 'knowledge_points'; checkbox.value = String(point.id);
          label.append(checkbox, document.createTextNode(' ' + point.name));
          wrapper.append(label); points.append(wrapper);
        }
        if (!data.points.length) points.textContent = '这门课程还没有知识点，可以直接保存错题。';
      } catch {
        if (thisRequest === requestNumber) points.textContent = '知识点加载失败，可先不选知识点保存，稍后编辑补充。';
      }
    });
  }
}
const reviewForm = document.querySelector('[data-review-form]');
if (reviewForm) {
  const dateInput = reviewForm.querySelector('[name="next_review_date"]');
  let customized = Boolean(dateInput.value);
  const preview = reviewForm.querySelector('[data-schedule-preview]');
  dateInput.addEventListener('input', () => { customized = Boolean(dateInput.value); });
  reviewForm.querySelectorAll('[name="rating"]').forEach(radio => {
    radio.addEventListener('change', () => {
      if (preview) preview.textContent = customized ? '使用你选择的日期：' + dateInput.value : 'FSRS建议复习日期：' + (reviewForm.dataset[radio.value] || '暂不可用') + '。日期留空会按提交时的最新状态计算。';
    });
  });
}
