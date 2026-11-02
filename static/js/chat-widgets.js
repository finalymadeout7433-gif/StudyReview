'use strict';
(() => {
  // Build rich text with text nodes only. Model output never becomes HTML.
  function inline(parent, text) {
    const parts=text.split(/(`[^`\n]+`|\*\*[^*\n]+\*\*)/g);
    parts.forEach(part=>{if(part.startsWith('`')&&part.endsWith('`')){const code=document.createElement('code');code.textContent=part.slice(1,-1);parent.append(code);}else if(part.startsWith('**')&&part.endsWith('**')){const strong=document.createElement('strong');strong.textContent=part.slice(2,-2);parent.append(strong);}else parent.append(document.createTextNode(part));});
  }
  function richText(text) {
    const root=document.createElement('div');root.className='mi-rich-text';
    let code=null,lines=[],list=null;
    const flush=()=>{if(!lines.length)return;const p=document.createElement('p');inline(p,lines.join('\n'));root.append(p);lines=[];};
    for(const line of String(text||'').split('\n')){
      if(line.trim().startsWith('```')){flush();list=null;if(code){root.append(code);code=null;}else{code=document.createElement('pre');code.append(document.createElement('code'));}continue;}
      if(code){code.firstChild.textContent+=line+'\n';continue;}
      const heading=line.match(/^#{1,4}\s+(.+)$/),bullet=line.match(/^\s*(?:[-*]|\d+[.)])\s+(.+)$/);
      if(heading){flush();list=null;const h=document.createElement('h4');inline(h,heading[1]);root.append(h);}
      else if(bullet){flush();if(!list){list=document.createElement('ul');root.append(list);}const li=document.createElement('li');inline(li,bullet[1]);list.append(li);}
      else if(!line.trim()){flush();list=null;}else{list=null;lines.push(line);}
    }
    flush();if(code)root.append(code);return root;
  }
  function messageNode(item) {
    const li=document.createElement('li');li.className='mi-message';li.dataset.role=item.role;li.dataset.messageId=item.id;
    const head=document.createElement('div');head.className='mi-message-heading';
    const name=document.createElement('span');name.textContent=item.role==='user'?'你':item.role==='assistant'?'拾习助手':'系统';head.append(name);
    const time=document.createElement('time');time.textContent=new Intl.DateTimeFormat('zh-CN',{hour:'2-digit',minute:'2-digit'}).format(new Date(item.created_at));head.append(time);li.append(head);
    li.append(richText(item.text));
    if(item.attachments?.length){const gallery=document.createElement('div');gallery.className='image-gallery';item.attachments.forEach(image=>{const figure=document.createElement('figure');figure.append(StudyImages.previewButton(image));gallery.append(figure);});li.append(gallery);}
    if(item.text){const copy=document.createElement('button');copy.type='button';copy.className='mi-copy-message';copy.textContent='复制';copy.setAttribute('aria-label','复制消息');copy.addEventListener('click',async()=>{try{await navigator.clipboard.writeText(item.text);copy.textContent='已复制';}catch{copy.textContent='复制失败';}setTimeout(()=>copy.textContent='复制',1800);});li.append(copy);}
    return li;
  }
  window.StudyChat={richText,messageNode};
  const panel=document.getElementById('mi-panel');if(!panel)return;
  const $=id=>document.getElementById(id),text=$('mi-text'),select=$('mi-session');
  function sync(){
    const hasMessages=$('mi-message-log').children.length>0;
    $('mi-empty').hidden=hasMessages||panel.classList.contains('is-thinking');$('mi-message-log').hidden=!hasMessages;
    const title=select.selectedOptions[0]?.textContent?.split(' · ')[0];$('mi-chat-title').textContent=title||'新对话';
    $('mi-no-sessions').hidden=select.options.length>0;$('mi-session-list').replaceChildren();
    [...select.options].forEach(option=>{const button=document.createElement('button');button.type='button';button.className='mi-session-item';button.textContent=option.textContent.split(' · ')[0];button.title=option.textContent;button.setAttribute('aria-current',String(option.selected));button.addEventListener('click',()=>{select.value=option.value;select.dispatchEvent(new Event('change'));panel.classList.remove('mi-history-open');});$('mi-session-list').append(button);});
    text.style.height='auto';text.style.height=Math.min(150,Math.max(50,text.scrollHeight))+'px';
  }
  document.addEventListener('study-assistant-ui',sync);
  new MutationObserver(sync).observe(select,{childList:true,subtree:true,characterData:true});
  new MutationObserver(()=>{const filled=$('mi-message-log').children.length>0;$('mi-empty').hidden=filled||panel.classList.contains('is-thinking');$('mi-message-log').hidden=!filled;}).observe($('mi-message-log'),{childList:true});
  text.addEventListener('input',()=>{text.style.height='auto';text.style.height=Math.min(150,Math.max(50,text.scrollHeight))+'px';});
  text.addEventListener('keydown',event=>{if(event.key==='Enter'&&!event.shiftKey&&!event.isComposing&&event.keyCode!==229){event.preventDefault();$('mi-composer').requestSubmit();}});
  panel.querySelectorAll('[data-chat-prompt]').forEach(button=>button.addEventListener('click',()=>{text.value=button.dataset.chatPrompt;text.dispatchEvent(new Event('input'));text.focus();}));
  function tools(){panel.querySelector('[data-mi-pane=chat]').click();$('mi-composer-options').open=!$('mi-composer-options').open;$('mi-more-menu').open=false;}
  $('mi-compose-tools').addEventListener('click',tools);$('mi-open-tools').addEventListener('click',tools);
  $('mi-history-toggle').addEventListener('click',()=>{$('mi-history-toggle').setAttribute('aria-expanded',String(panel.classList.toggle('mi-history-open')));});
  $('mi-maximize').addEventListener('click',()=>{const full=panel.classList.toggle('mi-maximized');$('mi-maximize').setAttribute('aria-pressed',String(full));$('mi-maximize').textContent=full?'还原':'展开';});
  sync();
})();
