'use strict';
(() => {
  const clamp=(v,min,max)=>Math.max(min,Math.min(max,v));
  function selection(a,b,width,height){const x=clamp(Math.min(a.x,b.x),0,width),y=clamp(Math.min(a.y,b.y),0,height);return{x,y,width:clamp(Math.max(a.x,b.x),0,width)-x,height:clamp(Math.max(a.y,b.y),0,height)-y};}
  function fit(width,height,max=4096){const ratio=Math.min(1,max/Math.max(width,height));return{width:Math.max(1,Math.round(width*ratio)),height:Math.max(1,Math.round(height*ratio))};}
  async function withScreenFrame(source,read,timeoutMs=30000){
    let stream=null,done=false,timer;
    const stop=value=>value?.getTracks().forEach(track=>track.stop());
    const work=(async()=>{const value=await source();if(done){stop(value);return null;}stream=value;return read(value);})();
    try{return await Promise.race([work,new Promise((_,reject)=>{timer=setTimeout(()=>{const error=new Error('截图选择超时');error.name='TimeoutError';reject(error);},timeoutMs);})]);}
    finally{done=true;clearTimeout(timer);stop(stream);}
  }
  if(typeof module!=='undefined')module.exports={selection,fit,withScreenFrame};
  if(typeof document==='undefined')return;
  const $=id=>document.getElementById(id),panel=$('mi-panel');if(!panel)return;
  const dialog=$('mi-crop-dialog'),canvas=$('mi-crop-canvas'),ctx=canvas.getContext('2d'),editor=panel.querySelector('[data-image-editor=chat]').imageEditor;
  let frame=null,rect=null,start=null,nonce=0,cropBusy=false;
  const note=text=>{$('mi-feedback').textContent=text;};
  function reset(){frame=null;rect=null;start=null;canvas.width=canvas.height=1;$('mi-crop-confirm').disabled=true;$('mi-crop-size').textContent='';}
  function draw(){if(!frame)return;ctx.clearRect(0,0,canvas.width,canvas.height);ctx.drawImage(frame,0,0);if(rect){ctx.fillStyle='rgba(18,35,30,.48)';ctx.fillRect(0,0,canvas.width,canvas.height);ctx.drawImage(frame,rect.x,rect.y,rect.width,rect.height,rect.x,rect.y,rect.width,rect.height);ctx.strokeStyle='#79dfbc';ctx.lineWidth=Math.max(2,canvas.width/700);ctx.strokeRect(rect.x,rect.y,rect.width,rect.height);}$('mi-crop-confirm').disabled=!rect||rect.width<8||rect.height<8;$('mi-crop-size').textContent=rect?`${Math.round(rect.width)} × ${Math.round(rect.height)}`:'';}
  const point=event=>{const box=canvas.getBoundingClientRect();return{x:(event.clientX-box.left)*canvas.width/box.width,y:(event.clientY-box.top)*canvas.height/box.height};};
  canvas.addEventListener('pointerdown',event=>{if(!frame)return;start=point(event);rect=null;canvas.setPointerCapture(event.pointerId);draw();});
  canvas.addEventListener('pointermove',event=>{if(!start)return;rect=selection(start,point(event),canvas.width,canvas.height);draw();});
  canvas.addEventListener('pointerup',event=>{if(!start)return;rect=selection(start,point(event),canvas.width,canvas.height);start=null;draw();});
  canvas.addEventListener('pointercancel',()=>{start=null;rect=null;draw();});
  dialog.addEventListener('close',reset);$('mi-crop-cancel').addEventListener('click',()=>dialog.close());
  function cancelCapture(){nonce++;if(dialog.open)dialog.close();reset();}
  panel.addEventListener('close',cancelCapture);
  $('mi-new-session').addEventListener('click',()=>{cancelCapture();$('mi-capture-help').hidden=true;});
  $('mi-session').addEventListener('change',cancelCapture);
  async function addCrop(region){
    if(!frame||editor.pending||cropBusy)return;cropBusy=true;
    try{const ticket=nonce,output=document.createElement('canvas');output.width=Math.round(region.width);output.height=Math.round(region.height);output.getContext('2d').drawImage(frame,region.x,region.y,region.width,region.height,0,0,output.width,output.height);const blob=await new Promise(resolve=>output.toBlob(resolve,'image/png'));if(!blob||ticket!==nonce||!panel.open||!dialog.open)return;dialog.close();await editor.add([new File([blob],'题目截图.png',{type:'image/png'})]);$('mi-text').focus();}
    finally{cropBusy=false;}
  }
  $('mi-crop-confirm').addEventListener('click',()=>{if(rect&&rect.width>=8&&rect.height>=8)addCrop(rect).catch(()=>note('截图未能加入，请重试。'));});
  $('mi-crop-whole').addEventListener('click',()=>{if(frame)addCrop({x:0,y:0,width:frame.width,height:frame.height}).catch(()=>note('截图未能加入，请重试。'));});
  $('mi-capture').addEventListener('click',async()=>{
    if(editor.pending)return;
    $('mi-capture-help').hidden=false;
    if(!navigator.mediaDevices?.getDisplayMedia){note('可使用 Windows 截图，再粘贴到输入框。');$('mi-text').focus();return;}
    const ticket=++nonce;let video=null;$('mi-capture').disabled=true;
    try{
      const captured=await withScreenFrame(()=>navigator.mediaDevices.getDisplayMedia({video:true,audio:false}),async stream=>{
        if(ticket!==nonce||!panel.open)return null;
        video=document.createElement('video');video.muted=true;video.srcObject=stream;await video.play();
        if(ticket!==nonce||!panel.open)return null;
        if(!video.videoWidth||!video.videoHeight)throw new Error('无截图画面');
        const size=fit(video.videoWidth,video.videoHeight),image=document.createElement('canvas');image.width=size.width;image.height=size.height;image.getContext('2d').drawImage(video,0,0,size.width,size.height);return image;
      });
      if(!captured||ticket!==nonce||!panel.open)return;
      frame=captured;canvas.width=frame.width;canvas.height=frame.height;rect=null;draw();dialog.showModal();note('');
    }catch(error){if(ticket===nonce)note(error.name==='NotAllowedError'?'已取消截图。':'当前窗口无法直接截图，请按 Win + Shift + S 后粘贴。');}
    finally{if(video)video.srcObject=null;$('mi-capture').disabled=false;}
  });
  $('mi-paste-image').addEventListener('click',async()=>{
    try{const items=await navigator.clipboard.read(),files=[];for(const item of items){const type=item.types.find(type=>['image/png','image/jpeg','image/webp'].includes(type));if(type){const blob=await item.getType(type);files.push(new File([blob],'题目截图.png',{type}));}}if(files.length)await editor.add(files);else note('剪贴板中没有图片，请先截图。');}
    catch{note('请在输入框按 Ctrl + V 粘贴截图。');}$('mi-text').focus();
  });
})();
