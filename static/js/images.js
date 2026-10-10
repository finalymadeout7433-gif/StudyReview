'use strict';
(() => {
  const roles = {question:'题干', original_answer:'原答', correct_answer:'参考答案', error_reason:'错因'};
  const csrf = () => document.querySelector('input[name=csrfmiddlewaretoken]')?.value || '';
  const safeMedia = value => typeof value === 'string' && /^\/attachments\/[0-9a-f-]{36}\/(thumbnail\/)?$/.test(value);
  const viewer = document.getElementById('learning-image-viewer');
  document.addEventListener('click', event => {
    const trigger = event.target.closest('[data-image-open]');
    if (trigger && viewer && safeMedia(trigger.dataset.imageUrl)) {
      const img = document.getElementById('learning-image-full');
      img.src = trigger.dataset.imageUrl; img.alt = trigger.dataset.imageName || '学习图片';
      if (!viewer.open) viewer.showModal();
    }
    if (event.target.closest('[data-image-close]')) viewer?.close();
  });
  viewer?.addEventListener('close', () => document.getElementById('learning-image-full').removeAttribute('src'));
  function previewButton(item) {
    const button = document.createElement('button'); button.type = 'button'; button.className = 'image-preview';
    button.dataset.imageOpen = ''; button.dataset.imageUrl = safeMedia(item.url) ? item.url : '';
    button.dataset.imageName = item.name || item.display_name || '学习图片';
    const img = document.createElement('img'); img.alt = button.dataset.imageName;
    if (safeMedia(item.thumbnail_url)) img.src = item.thumbnail_url;
    img.loading = 'lazy'; button.append(img); return button;
  }
  class ImageEditor {
    constructor(element) {
      this.element = element; this.mode = element.dataset.imageEditor; this.items = []; this.pending = 0;
      this.limit = this.mode === 'question' ? 24 : 4;
      this.list = element.querySelector('[data-image-list]'); this.status = element.querySelector('[data-image-status]');
      this.input = element.querySelector('[data-image-input]'); this.form = element.closest('form');
      this.payload = this.form?.querySelector('[name=image_payload]');
      element.querySelector('[data-image-choose]')?.addEventListener('click', () => this.input.click());
      this.input.addEventListener('change', () => { this.add(this.input.files); this.input.value = ''; });
      const drop = element.querySelector('[data-image-drop]');
      drop.addEventListener('dragover', event => { event.preventDefault(); drop.classList.add('is-dragging'); });
      drop.addEventListener('dragleave', () => drop.classList.remove('is-dragging'));
      drop.addEventListener('drop', event => { event.preventDefault(); drop.classList.remove('is-dragging'); this.add(event.dataTransfer.files); });
      this.form?.addEventListener('paste', event => {
        const files = [...(event.clipboardData?.items || [])].filter(item => item.kind === 'file').map(item => item.getAsFile()).filter(Boolean);
        if (files.length) { event.preventDefault(); this.add(files); }
      });
      this.form?.addEventListener('submit', event => {
        if (this.pending) { event.preventDefault(); event.stopImmediatePropagation(); this.status.textContent = '图片正在上传，请等待完成后再提交。'; }
      }, true);
      if (this.mode === 'question') {
        const initial = document.getElementById('initial-question-images');
        try { this.items = JSON.parse(initial?.textContent || '[]').filter(item => safeMedia(item.url)).slice(0,24); }
        catch { this.status.textContent = '原有图片列表读取失败，请刷新后重试。'; }
      }
      element.imageEditor = this; this.render();
    }
    async add(files) {
      for (const file of files) {
        if (this.items.length + this.pending >= this.limit) { this.status.textContent = `本次最多保留 ${this.limit} 张图片。`; break; }
        if (file.size > 8*1024*1024) { this.status.textContent = `${file.name} 超过8 MB，请选择较小的图片。`; continue; }
        if (!['image/png','image/jpeg','image/webp'].includes(file.type)) { this.status.textContent = '请选择 PNG、JPEG 或 WebP 静态图片。'; continue; }
        this.pending++; this.status.textContent = '正在校验并保存图片…';
        try {
          const body = new FormData(); body.append('file',file);
          const response = await fetch('/attachments/upload/', {method:'POST', credentials:'same-origin', headers:{'X-CSRFToken':csrf()}, body});
          const data = await response.json();
          if (!response.ok) throw new Error(typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail || data.error || '图片保存失败。'));
          if (!safeMedia(data.url) || !safeMedia(data.thumbnail_url)) throw new Error('图片响应格式不正确。');
          if (!this.items.some(item => item.id === data.id)) this.items.push({...data,role:'question'});
          this.status.textContent = `已保存 ${this.items.length} 张图片。`; this.render();
        } catch (error) { this.status.textContent = error.message || '上传失败，请再次选择图片重试。'; }
        finally { this.pending--; }
      }
    }
    render() {
      this.list.replaceChildren();
      this.items.forEach((item,index) => {
        const card = document.createElement('div'); card.className = 'image-edit-card';
        card.append(previewButton(item));
        const name = document.createElement('p'); name.textContent = item.name || item.display_name || '学习图片'; card.append(name);
        if (this.mode === 'question') {
          const select = document.createElement('select'); select.setAttribute('aria-label',`${name.textContent}的用途`);
          for (const [value,label] of Object.entries(roles)) { const option = new Option(label,value); select.add(option); }
          select.value = item.role || 'question'; select.addEventListener('change', () => { item.role = select.value; this.sync(); }); card.append(select);
          if (index) {
            const move = document.createElement('button'); move.type='button'; move.className='text-button'; move.textContent='前移 ↑';
            move.addEventListener('click', () => { [this.items[index-1],this.items[index]]=[this.items[index],this.items[index-1]]; this.render(); }); card.append(move);
          }
        }
        const remove=document.createElement('button'); remove.type='button'; remove.className='text-button'; remove.textContent='移除';
        remove.addEventListener('click', () => { this.items.splice(index,1); this.render(); this.status.textContent='已从本次内容移除；已保存的历史图片继续保留。'; }); card.append(remove); this.list.append(card);
      }); this.sync();
    }
    sync() { if (this.payload) this.payload.value=JSON.stringify(this.items.map(item => ({id:item.id,role:item.role || 'question'}))); }
    ids() { return this.items.map(item => item.id); }
    clear() { this.items=[]; this.render(); this.status.textContent=''; }
  }
  document.querySelectorAll('[data-image-editor]').forEach(element => new ImageEditor(element));
  window.StudyImages = {safeMedia, previewButton};
})();
