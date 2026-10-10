'use strict';
(() => {
  const panel=document.getElementById('mi-panel'); if (!panel) return;
  const $=id=>document.getElementById(id), uuid=()=>crypto.randomUUID();
  const csrf=()=>panel.querySelector('input[name=csrfmiddlewaretoken]')?.value || '';
  const feedback=text=>{$('mi-feedback').textContent=text;};
  let session=null, sessionCursor=null, messageCursor=null, draftCursor=null, courses=[], target=null;
  let submission=null, pending=false, opening=false, loaded=false, draftBusy=false, targetCursor=null;
  const confirmationKeys=new Map();
  const restoreKey='study-mi-view:'+document.body.dataset.userId;
  let restoredView=null;
  try{restoredView=JSON.parse(sessionStorage.getItem(restoreKey)||'null');sessionStorage.removeItem(restoreKey);}catch{}
  let openingWork=Promise.resolve();
  const selectedHistory=new Set();
  const editor=panel.querySelector('[data-image-editor=chat]').imageEditor;
  const composers=new Map();
  let sessionEpoch=0, messageRequest=0, draftRequest=0, targetRequest=0, candidateRequest=0;
  function saveComposer(id=session) {
    if(id)composers.set(id,{text:$('mi-text').value,images:editor.items.map(item=>({...item})),
      course:$('mi-ai-course').value,useHistory:$('mi-use-selected-context').checked,
      history:[...selectedHistory],target,submission,targetKind:$('mi-target-kind').value,
      targetId:$('mi-target-id').value,targetPreview:$('mi-target-preview').textContent,
      action:$('mi-action').value,query:$('mi-target-query').value});
  }
  function activateSession(id) {
    saveComposer(session||id);session=id;sessionEpoch++;targetRequest++;candidateRequest++;messageCursor=null;draftCursor=null;
    const saved=composers.get(id);
    $('mi-text').value=saved?.text||'';editor.items=(saved?.images||[]).map(item=>({...item}));editor.render();
    $('mi-ai-course').value=saved?.course||'';$('mi-use-selected-context').checked=saved?.useHistory||false;
    selectedHistory.clear();(saved?.history||[]).forEach(item=>selectedHistory.add(item));
    target=saved?.target||null;submission=saved?.submission||null;
    $('mi-target-kind').value=saved?.targetKind||'question';$('mi-target-id').value=saved?.targetId||'';
    $('mi-target-preview').textContent=saved?.targetPreview||'尚未选择修改对象。';
    $('mi-action').value=saved?.action||'auto';$('mi-target-query').value=saved?.query||'';
    $('mi-target-candidates').replaceChildren();$('mi-more-targets').hidden=true;targetCursor=null;
    $('mi-message-log').replaceChildren();$('mi-draft-list').replaceChildren();
  }
  async function api(url,method='GET',data) {
    const response=await fetch(url,{method,credentials:'same-origin',redirect:'error',headers:{'Accept':'application/json',...(data!==undefined?{'Content-Type':'application/json'}:{}),...(method!=='GET'?{'X-CSRFToken':csrf()}:{})},...(data!==undefined?{body:JSON.stringify(data)}:{})});
    let result; try {result=await response.json();} catch {throw new Error('服务未返回可读结果，请保留输入并重试。');}
    if (!response.ok) { const detail=result.detail || result.error || '请求未完成。'; throw new Error(typeof detail==='string'?detail:Array.isArray(detail)?detail.join('；'):JSON.stringify(detail)); }
    return result;
  }
  function pane(name) {
    panel.querySelectorAll('.mi-pane').forEach(item=>item.hidden=item.id!==`mi-${name}`);
    panel.querySelectorAll('[data-mi-pane]').forEach(button=>button.setAttribute('aria-pressed',String(button.dataset.miPane===name)));
    if (name==='config') refreshConfig().catch(error=>feedback(error.message));
  }
  function openPanel() {
    if (panel.open) return;
    if (matchMedia('(min-width:1100px)').matches) {
      panel.show(); document.body.classList.add('mi-open');
    } else {document.body.classList.remove('mi-open');panel.showModal();}
  }
  panel.addEventListener('close',()=>{if(!panel.open)document.body.classList.remove('mi-open');});
  matchMedia('(min-width:1100px)').addEventListener('change',()=>{
    if (!panel.open) return;
    panel.close(); document.body.classList.remove('mi-open'); openPanel();
  });
  document.addEventListener('keydown',event=>{
    if(event.key==='Escape'&&panel.open&&!document.getElementById('learning-image-viewer').open)panel.close();
  });
  panel.querySelectorAll('[data-mi-pane]').forEach(button=>button.addEventListener('click',()=>pane(button.dataset.miPane)));
  panel.querySelector('[data-mi-close]').addEventListener('click',()=>panel.close());
  $('mi-launcher').addEventListener('click',async()=>{
    openPanel();
    if (loaded || opening) return; opening=true;
    openingWork=(async()=>{
      await Promise.all([loadSessions(),loadContext(),refreshConfig()]);
      if(restoredView?.session&&/^[0-9a-f-]{36}$/i.test(restoredView.session)){
        const previous=session;activateSession(restoredView.session);
        try{await loadSession();}catch{activateSession(previous);if(session)await loadSession();}
        if(typeof restoredView.text==='string'&&!$('mi-text').value)$('mi-text').value=restoredView.text.slice(0,16000);
        restoredView=null;pane('drafts');feedback('修改已保存，本页已更新；原会话和预览已恢复。');
      }else if (!session) await newSession(); else await loadSession(); loaded=true;
    })();
    try {
      await openingWork;
    } catch(error) {feedback(error.message);} finally {opening=false;}
  });
  async function loadSessions(older=false) {
    const data=await api('/assistant/sessions/'+(older&&sessionCursor?`?before=${encodeURIComponent(sessionCursor)}`:''));
    if (!older) $('mi-session').replaceChildren();
    for (const item of data.sessions) { if (![...$('mi-session').options].some(option=>option.value===item.id)) $('mi-session').add(new Option(item.title+' · '+new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(item.created_at)),item.id)); }
    sessionCursor=data.older_cursor; $('mi-more-sessions').hidden=!data.has_more;
    if (!session&&data.sessions.length) activateSession(data.sessions[0].id);
    if (session) $('mi-session').value=session;
  }
  async function newSession() {
    const data=await api('/assistant/sessions/','POST',{title:'新会话',submission_key:uuid()});
    activateSession(data.session.id);
    await loadSessions(); await loadSession(); feedback('新会话已保存在本机。');
  }
  $('mi-new-session').addEventListener('click',async()=>{if(pending||draftBusy||opening||editor.pending)return;const button=$('mi-new-session');if(button.disabled)return;button.disabled=true;try{await newSession();}catch(error){feedback(error.message);}finally{button.disabled=false;}});
  $('mi-more-sessions').addEventListener('click',()=>loadSessions(true).catch(error=>feedback(error.message)));
  $('mi-session').addEventListener('change',()=>{
    if (pending||draftBusy||opening||editor.pending||$('mi-new-session').disabled) {$('mi-session').value=session;feedback('请等待会话读取、本次保存或图片上传完成后切换。');return;}
    activateSession($('mi-session').value);loadSession().catch(error=>feedback(error.message));
  });
  async function loadSession(older=false) {
    if (!session) return;
    const id=session,epoch=sessionEpoch,request=++messageRequest;
    const data=await api(`/assistant/sessions/${id}/`+(older&&messageCursor?`?before=${encodeURIComponent(messageCursor)}`:''));
    if(session!==id||sessionEpoch!==epoch||messageRequest!==request)return;
    if(![...$('mi-session').options].some(option=>option.value===id))$('mi-session').add(new Option(data.session.title,id));
    $('mi-session').value=id;
    if (!older) {$('mi-message-log').replaceChildren();$('mi-draft-list').replaceChildren();}
    const fragment=document.createDocumentFragment(); data.messages.forEach(item=>fragment.append(messageNode(item)));
    if (older) $('mi-message-log').prepend(fragment); else $('mi-message-log').append(fragment);
    messageCursor=data.older_cursor; $('mi-older-messages').hidden=!data.has_older;
    if (!older) {await loadDrafts(false,id,epoch);if(session===id&&sessionEpoch===epoch)$('mi-message-log').scrollTop=$('mi-message-log').scrollHeight;}
  }
  $('mi-older-messages').addEventListener('click',()=>loadSession(true).catch(error=>feedback(error.message)));
  async function loadDrafts(older=false,id=session,epoch=sessionEpoch) {
    if(!session)return;
    const request=++draftRequest;
    const data=await api(`/assistant/sessions/${id}/drafts/`+(older&&draftCursor?`?before=${encodeURIComponent(draftCursor)}`:''));
    if(session!==id||sessionEpoch!==epoch||draftRequest!==request)return;
    if(!older)$('mi-draft-list').replaceChildren();
    data.drafts.forEach(renderDraft);draftCursor=data.older_cursor;$('mi-more-drafts').hidden=!data.has_more;
  }
  $('mi-more-drafts').addEventListener('click',()=>loadDrafts(true).catch(error=>feedback(error.message)));
  function messageNode(item) {
    const li=document.createElement('li'); li.className='mi-message'; li.dataset.role=item.role; li.dataset.messageId=item.id;
    const head=document.createElement('div');head.className='mi-message-heading';
    const who=document.createElement('span');who.textContent=item.role==='user'?'你':item.role==='assistant'?'AI 回复':'系统记录';head.append(who);
    const time=document.createElement('time');time.textContent=new Intl.DateTimeFormat('zh-CN',{timeZone:'Asia/Shanghai',month:'2-digit',day:'2-digit',hour:'2-digit',minute:'2-digit'}).format(new Date(item.created_at));head.append(time);
    if (item.role==='user'||item.role==='assistant') {
      const label=document.createElement('label'),check=document.createElement('input');check.type='checkbox';check.checked=selectedHistory.has(item.id);
      check.addEventListener('change',()=>{if(check.checked){if(selectedHistory.size>=19){check.checked=false;feedback('最多主动选择19条历史消息。');return;}selectedHistory.add(item.id);}else selectedHistory.delete(item.id);submission=null;});
      label.append(check,document.createTextNode('选为上下文'));head.append(label);
    }
    li.append(head);const text=document.createElement('p');text.textContent=item.text;li.append(text);
    if (item.attachments?.length) {
      const gallery=document.createElement('div');gallery.className='image-gallery';
      item.attachments.forEach(image=>{const figure=document.createElement('figure');figure.append(StudyImages.previewButton(image));gallery.append(figure);});li.append(gallery);
    }
    if (item.selection) {
      const selection=document.createElement('p');selection.className='help-text';
      selection.textContent=[item.selection.target?`本次选定${item.selection.target.kind==='task'?'任务':'错题'} #${item.selection.target.id}`:'',item.selection.course?`本次课程：${item.selection.course.name}`:'',item.selection.history_message_ids?.length?`主动选入历史：${item.selection.history_message_ids.length} 条`:''].filter(Boolean).join(' · ');
      if(selection.textContent)li.append(selection);
    }return li;
  }
  $('mi-text').addEventListener('input',()=>{if(!pending)submission=null;});
  $('mi-use-selected-context').addEventListener('change',()=>{if(!pending)submission=null;});
  $('mi-ai-course').addEventListener('change',()=>{if(!pending)submission=null;});
  $('mi-composer').addEventListener('submit',async event=>{
    event.preventDefault(); if(pending||draftBusy||editor.pending)return;
    if(opening){feedback('会话正在读取，请稍候提交；输入继续保留。');return;}
    const submittedText=$('mi-text').value,text=submittedText.trim(),submittedImages=editor.ids();
    let intent=$('mi-action').value;
    if(intent==='auto'&&!target&&/(修改|编辑|推迟|延期|改成|改为|完成|整理|更新|帮我改)/.test(text)){
      if(/任务|作业|计划|笔记|说明/.test(text))intent=/笔记|说明/.test(text)?'task_note':'task';
      else if(/错题|题目|题干|答案|错因/.test(text))intent='question';
    }
    const requiredKind=['task','task_note'].includes(intent)?'task':intent==='question'?'question':null;
    if(requiredKind&&(!target||target.kind!==requiredKind)){
      $('mi-action').value=intent;$('mi-target-kind').value=requiredKind;$('mi-target-tools').open=true;
      await searchTargets();feedback('请选择要修改的具体对象，输入已保留；选择后再次点击生成预览。');return;
    }
    if(intent==='create_question'&&!$('mi-ai-course').value){
      $('mi-target-tools').open=true;$('mi-ai-course').focus();feedback('请先选择新错题所属课程，原输入继续保留。');return;
    }
    const submittedHistory=$('mi-use-selected-context').checked?[...selectedHistory]:[];
    const submittedTarget=intent==='chat'||intent==='create_question'?null:target;
    const submittedCourse=$('mi-ai-course').value;
    if(!text&&!submittedImages.length){feedback('请填写问题或添加图片。');return;}
    pending=true;$('mi-send').disabled=true;feedback('正在保存本次提交…');
    try {
      if(!session)await newSession();
      const body={text,attachment_ids:submittedImages,context_message_ids:submittedHistory};
      if(submittedTarget){
        body.selected_target={kind:submittedTarget.kind,id:submittedTarget.target_id,expected_version:submittedTarget.expected_version};
        if(intent==='task_note')body.selected_target.field_scope=['description'];
      }
      if(submittedCourse)body.selected_course_id=Number(submittedCourse);
      const fingerprint=JSON.stringify(body);
      if(!submission||submission.fingerprint!==fingerprint)submission={fingerprint,key:uuid()};
      const data=await api(`/assistant/sessions/${session}/messages/`,'POST',{...body,submission_key:submission.key});
      submission=null;if($('mi-text').value===submittedText)$('mi-text').value='';
      editor.items=editor.items.filter(item=>!submittedImages.includes(item.id));editor.render();
      submittedHistory.forEach(id=>selectedHistory.delete(id));
      if(!selectedHistory.size)$('mi-use-selected-context').checked=false;saveComposer();
      await loadSession();await refreshConfig();
      feedback(data.response?.role==='assistant'?'回复和草稿已保存，请核对后确认。':'问题已保存在本机；请查看系统记录中的连接状态。');
      if(data.drafts?.length)pane('drafts');
    }catch(error){feedback(error.message+' 输入已保留；重试相同内容会沿用提交编号。');}
    finally{pending=false;$('mi-send').disabled=false;}
  });
  async function loadContext() {
    const data=await api('/assistant/context/'); courses=data.courses;
    $('mi-draft-course').replaceChildren(new Option('请选择课程',''));
    $('mi-ai-course').replaceChildren(new Option('不发送课程信息',''));
    for(const course of courses){$('mi-draft-course').add(new Option(course.name,course.id));$('mi-ai-course').add(new Option(course.name,course.id));}
    const today=new Intl.DateTimeFormat('sv-SE',{timeZone:'Asia/Shanghai',year:'numeric',month:'2-digit',day:'2-digit'}).format(new Date());
    $('mi-draft-form').elements.next_review_date.value=today;
  }
  $('mi-draft-course').addEventListener('change',()=>{
    const course=courses.find(item=>String(item.id)===$('mi-draft-course').value);$('mi-draft-points').replaceChildren();
    for(const point of course?.knowledge_points||[])$('mi-draft-points').add(new Option(point.name,point.id));
  });
  const labels={id:'编号',course_id:'课程编号',course_name:'课程名称',course_archived:'课程已归档',is_archived:'已归档',knowledge_points:'知识点',title:'标题',content:'题干',original_answer:'原答',correct_answer:'参考答案',error_reason:'错因',next_review_date:'下次复习',knowledge_point_ids:'知识点编号',attachment_ids:'图片编号',images:'图片用途与顺序',updated_at:'更新时间',completed_at:'完成时间',status:'状态',priority:'优先级',due_date:'截止日期',description:'任务说明 / 笔记',name:'名称'};
  const valueLabels={status:{todo:'未完成',done:'已完成'},priority:{low:'低',normal:'普通',high:'高'},imageRole:{question:'题干',original_answer:'原答',correct_answer:'参考答案',error_reason:'错因'}};
  function readableValue(key,value) {
    if(value===null)return'空';if(typeof value==='boolean')return value?'是':'否';
    if(key==='knowledge_points'&&Array.isArray(value))return value.map(item=>Array.isArray(item)?`#${item[0]} ${item[1]}`:typeof item==='object'?`#${item.id} ${item.name}`:String(item)).join('、')||'未关联';
    if(key==='images'&&Array.isArray(value))return value.map(item=>`${valueLabels.imageRole[item[0]]||'学习图片'} · 第${Number(item[1])+1}张 · ${item[2]}`).join('；')||'无';
    if(Array.isArray(value))return value.map(item=>typeof item==='object'?readable(item):String(item)).join('、')||'无';
    if(typeof value==='object')return readable(value);
    return valueLabels[key]?.[value]||String(value);
  }
  function readable(snapshot) {return Object.entries(snapshot||{}).map(([key,value])=>`${labels[key]||'其他字段'}：${readableValue(key,value)}`).join('\n');}
  function renderDraft(draft) {
    const existing=$('mi-draft-list').querySelector('[data-draft-id="'+draft.id+'"]');if(existing)existing.remove();
    const card=document.createElement('article');card.className='mi-draft-card';card.dataset.draftId=draft.id;
    const h=document.createElement('h3');h.textContent=draft.title||({'create_question':'新增错题','update_question':'修改错题','update_task':'修改任务'}[draft.operation]||'待确认草稿');card.append(h);
    const identity=document.createElement('p');identity.className='mi-draft-target';
    identity.textContent=(draft.operation==='update_task'?'任务':draft.operation==='update_question'?'错题':'新错题')+
      (draft.target_id?' #'+draft.target_id:'')+' · '+(draft.after.course_name||'')+
      (draft.before.title?' · '+draft.before.title:'');card.append(identity);
    const status=document.createElement('p');status.className='help-text';status.textContent=draft.status==='applied'?'已确认保存':draft.cancelled?'已取消 · 学习内容未修改':draft.expired?'草稿已过期，请重新生成':'待确认 · 以下字段将发生变化';card.append(status);
    const table=document.createElement('table');table.className='mi-change-table';table.setAttribute('aria-label','修改字段对比');
    const head=document.createElement('tr');for(const label of ['字段','修改前','确认后']){const th=document.createElement('th');th.textContent=label;head.append(th);}table.append(head);
    for(const key of Object.keys(draft.payload||{})){
      if(key==='course_id')continue;
      const tr=document.createElement('tr');tr.dataset.changedField=key;
      for(const text of [labels[key]||key,readableValue(key,draft.before[key]??null),readableValue(key,draft.after[key]??null)]){
        const td=document.createElement('td');td.textContent=text;tr.append(td);
      }table.append(tr);
    }card.append(table);
    const details=document.createElement('details'),summary=document.createElement('summary'),pre=document.createElement('pre');
    summary.textContent='查看完整对象预览';pre.className='mi-draft-data';pre.textContent=readable(draft.after);details.append(summary,pre);card.append(details);
    for(const side of ['before','after']){
      const images=draft.images?.[side]||[];
      if(images.length){const gallery=document.createElement('div');gallery.className='image-gallery';
        images.forEach(image=>{const figure=document.createElement('figure');figure.append(StudyImages.previewButton(image));gallery.append(figure);});card.append(gallery);}
    }
    if(draft.status==='pending'&&!draft.expired) {
      const button=document.createElement('button');button.type='button';button.className='button primary';button.dataset.draftConfirm=draft.id;button.textContent='确认修改并刷新本页';
      const cancel=document.createElement('button');cancel.type='button';cancel.className='button secondary';cancel.dataset.draftCancel=draft.id;cancel.textContent='取消这份草稿';
      button.addEventListener('click',async()=>{
        if(draftBusy||pending||editor.pending||button.disabled)return;
        draftBusy=true;button.disabled=true;cancel.disabled=true;const id=session,epoch=sessionEpoch;
        if(!confirmationKeys.has(draft.id))confirmationKeys.set(draft.id,uuid());
        try{
          const result=await api('/assistant/drafts/'+draft.id+'/confirm/','POST',{confirmation_token:draft.confirmation_token,submission_key:confirmationKeys.get(draft.id)});
          if(session!==id||sessionEpoch!==epoch)return;
          renderDraft(result.draft);feedback('修改已保存，正在更新本页…');
          try{sessionStorage.setItem(restoreKey,JSON.stringify({session:id,text:$('mi-text').value}));}catch{}
          location.reload();
        }catch(error){feedback(error.message);button.disabled=false;cancel.disabled=false;}
        finally{draftBusy=false;}
      });
      cancel.addEventListener('click',async()=>{
        if(draftBusy||pending||cancel.disabled)return;
        draftBusy=true;button.disabled=true;cancel.disabled=true;const id=session,epoch=sessionEpoch;
        try{const result=await api('/assistant/drafts/'+draft.id+'/cancel/','POST',{});
          if(session===id&&sessionEpoch===epoch){renderDraft(result.draft);feedback('草稿已取消，任务和错题没有改动。');}
        }catch(error){feedback(error.message);button.disabled=false;cancel.disabled=false;}
        finally{draftBusy=false;}
      });card.append(button,cancel);
    }
    if(draft.status==='applied'&&draft.applied_object_id){
      const link=document.createElement('a');link.className='back-link';link.href=draft.operation==='update_task'?'/tasks/':'/questions/'+Number(draft.applied_object_id)+'/';link.textContent='查看已保存内容 →';card.append(link);
    }$('mi-draft-list').append(card);
  }
  $('mi-draft-form').addEventListener('submit',async event=>{
    event.preventDefault();const form=event.currentTarget;if(!form.checkValidity()||pending||draftBusy||editor.pending)return;
    const button=form.querySelector('button[type=submit]');button.disabled=true;
    try {
      if(!session)await newSession();const payload={};
      for(const key of ['title','content','original_answer','correct_answer','error_reason','next_review_date'])payload[key]=form.elements[key].value.trim();
      payload.course_id=Number(form.elements.course_id.value);payload.knowledge_point_ids=[...$('mi-draft-points').selectedOptions].map(option=>Number(option.value));
      payload.attachment_ids=$('mi-draft-include-images').checked?editor.ids():[];
      const id=session,epoch=sessionEpoch;const data=await api(`/assistant/sessions/${id}/drafts/`,'POST',{operation:'create_question',payload,submission_key:uuid()});if(session!==id||sessionEpoch!==epoch)return;renderDraft(data.draft);feedback('草稿已生成，请核对后点击确认。');
    }catch(error){feedback(error.message);}finally{button.disabled=false;}
  });
  async function searchTargets(older=false) {
    if(pending||draftBusy||opening)return;
    const epoch=sessionEpoch,request=++candidateRequest,kind=$('mi-target-kind').value,query=$('mi-target-query').value.trim();
    const params=new URLSearchParams({kind,query});if(older&&targetCursor)params.set('before',String(targetCursor));
    try{
      const data=await api('/assistant/targets/?'+params.toString());
      if(epoch!==sessionEpoch||request!==candidateRequest)return;
      if(!older)$('mi-target-candidates').replaceChildren();
      for(const item of data.targets){
        const button=document.createElement('button');button.type='button';button.className='mi-target-choice text-button';button.dataset.candidateId=item.id;
        button.textContent=item.title+' · '+item.course_name+' · '+item.date+(item.status==='done'?' · 已完成':'');
        button.addEventListener('click',()=>selectTarget(item.kind,item.id));$('mi-target-candidates').append(button);
      }
      if(!data.targets.length){const text=document.createElement('p');text.textContent='没有匹配的可编辑对象。试试课程名或部分标题。';$('mi-target-candidates').append(text);}
      targetCursor=data.older_cursor;$('mi-more-targets').hidden=!data.has_more;
    }catch(error){if(epoch===sessionEpoch&&request===candidateRequest)feedback(error.message);}
  }
  async function selectTarget(kind,id) {
    if(pending||draftBusy)return;
    if(opening){feedback('会话正在读取，请稍候选择对象。');return;}
    if(!Number.isSafeInteger(id)||id<1){feedback('请选择一个要修改的对象。');return;}
    const epoch=sessionEpoch,request=++targetRequest;
    try{
      const data=await api('/assistant/targets/'+kind+'/'+id+'/');if(epoch!==sessionEpoch||request!==targetRequest)return;
      target={...data,kind,target_id:id};submission=null;
      if($('mi-ai-course').value&&Number($('mi-ai-course').value)!==data.snapshot.course_id)$('mi-ai-course').value='';
      $('mi-target-kind').value=kind;$('mi-target-id').value=id;
      if(!['task_note'].includes($('mi-action').value)||kind!=='task')$('mi-action').value=kind;
      $('mi-target-preview').textContent='本次仅修改'+(kind==='task'?'任务':'错题')+' #'+id+' · '+data.snapshot.course_name+'\n'+readable(data.snapshot);
      feedback('对象已选定，输入保持不变；点击生成修改预览。');updateSendLabel();
    }catch(error){if(epoch===sessionEpoch&&request===targetRequest){target=null;feedback(error.message);}}
  }
  function updateSendLabel(){
    if(!target)return;
    $('mi-send').textContent=$('mi-action').value==='chat'?'提交问题并请求 AI':'生成待确认修改';
  }
  $('mi-search-target').addEventListener('click',()=>searchTargets());
  $('mi-more-targets').addEventListener('click',()=>searchTargets(true));
  $('mi-target-query').addEventListener('keydown',event=>{if(event.key==='Enter'){event.preventDefault();searchTargets();}});
  $('mi-target-kind').addEventListener('change',()=>{
    if(pending||draftBusy)return;
    candidateRequest++;targetRequest++;target=null;submission=null;$('mi-action').value=$('mi-target-kind').value;
    $('mi-target-preview').textContent='尚未选择修改对象。';$('mi-target-candidates').replaceChildren();searchTargets();
  });
  $('mi-action').addEventListener('change',()=>{
    if(pending||draftBusy)return;submission=null;const mode=$('mi-action').value;
    if(['task','task_note','question'].includes(mode)){
      const kind=mode==='question'?'question':'task';$('mi-target-kind').value=kind;
      if(target&&target.kind!==kind)target=null;$('mi-target-tools').open=true;searchTargets();
    }updateSendLabel();
  });
  $('mi-load-target').addEventListener('click',()=>selectTarget($('mi-target-kind').value,Number($('mi-target-id').value)));
  document.addEventListener('click',async event=>{
    const button=event.target.closest('[data-mi-target]');if(!button||pending||draftBusy)return;
    $('mi-launcher').click();pane('chat');
    try{await openingWork;}catch{return;}
    $('mi-action').value=button.dataset.miAction||button.dataset.miTarget;$('mi-target-tools').open=true;
    selectTarget(button.dataset.miTarget,Number(button.dataset.miTargetId));
  });
  $('mi-clear-target').addEventListener('click',()=>{
    if(pending||draftBusy)return;targetRequest++;target=null;submission=null;
    $('mi-target-preview').textContent='尚未选择修改对象。';$('mi-send').textContent='提交问题并请求 AI';
  });
  const currentQuestion=location.pathname.match(/^\/questions\/(\d+)\/(edit\/|review\/)?$/);
  const currentTask=location.pathname.match(/^\/tasks\/(\d+)\/edit\/$/);
  if(currentQuestion||currentTask){
    $('mi-current-target').hidden=false;
    $('mi-current-target').addEventListener('click',()=>selectTarget(currentTask?'task':'question',Number((currentTask||currentQuestion)[1])));
  }
  async function refreshConfig() {
    const data=await api('/ai/config/');
    $('mi-provider-state').textContent=data.label||(data.enabled?'AI 已配置 · 待实际验证':'AI 未连接');
    $('mi-send').textContent=data.enabled?'提交问题并请求 AI':'保存问题';
    $('mi-offline-note').hidden=data.enabled;if(data.enabled)updateSendLabel();
    $('mi-budget-summary').textContent=data.configured?`累计上限：¥${data.budget_cny??data.budget}\n已估算：¥${data.spent_cny??data.spent}\n预留：¥${data.reserved_cny??data.reserved}\n剩余：¥${data.remaining_cny??data.remaining}\n不确定请求：${data.uncertain_requests||0}`:'尚未配置密钥或预算，当前不会调用 AI。';
    $('mi-disable-provider').disabled=!data.enabled;
  }
  $('mi-config-form').addEventListener('submit',async event=>{
    event.preventDefault();const form=event.currentTarget;if(!form.checkValidity())return;const button=form.querySelector('button[type=submit]');button.disabled=true;
    try{await api('/ai/config/','POST',{api_key:form.elements.api_key.value,budget_cny:form.elements.budget_cny.value,confirm_local_storage:form.elements.confirm_local_storage.checked,confirm_budget:form.elements.confirm_budget.checked,confirm_destination:form.elements.confirm_destination.checked,enable:true});
      form.reset();await refreshConfig();feedback('配置已加密保存在本机；尚未进行真实调用验证。');
    }catch(error){feedback(error.message);}finally{form.elements.api_key.value='';button.disabled=false;}
  });
  $('mi-disable-provider').addEventListener('click',async()=>{try{await api('/ai/config/','DELETE');await refreshConfig();feedback('AI 已停用，本地聊天记录继续保留。');}catch(error){feedback(error.message);}});
  if(restoredView)queueMicrotask(()=>$('mi-launcher').click());
})();
