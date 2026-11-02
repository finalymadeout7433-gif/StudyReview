const {test}=require('node:test');
const assert=require('node:assert/strict');
const {selection,fit,withScreenFrame}=require('../../static/js/chat-capture.js');
test('crop supports backwards drag and clamps to image edges',()=>{
  assert.deepEqual(selection({x:900,y:600},{x:-30,y:120},800,500),{x:0,y:120,width:800,height:380});
  assert.deepEqual(selection({x:40,y:30},{x:40,y:30},800,500),{x:40,y:30,width:0,height:0});
});
test('large capture preserves aspect and small captures are not enlarged',()=>{
  assert.deepEqual(fit(7680,4320),{width:4096,height:2304});
  assert.deepEqual(fit(640,480),{width:640,height:480});
});
test('all capture tracks stop before returning a frame',async()=>{
  const stopped=[],stream={getTracks:()=>[1,2].map(id=>({stop:()=>stopped.push(id)}))};
  assert.equal(await withScreenFrame(async()=>stream,async()=> 'frame'), 'frame');
  assert.deepEqual(stopped,[1,2]);
});
test('decoding failure still releases capture',async()=>{
  let stopped=false;const stream={getTracks:()=>[{stop:()=>stopped=true}]};
  await assert.rejects(withScreenFrame(async()=>stream,async()=>{throw Error('decode');}),/decode/);
  assert.equal(stopped,true);
});
test('late picker result is stopped and never decoded after timeout',async()=>{
  let finish,decoded=false,stopped=false;const source=new Promise(resolve=>finish=resolve);
  await assert.rejects(withScreenFrame(()=>source,async()=>{decoded=true;},10),{name:'TimeoutError'});
  finish({getTracks:()=>[{stop:()=>stopped=true}]});await new Promise(resolve=>setImmediate(resolve));
  assert.equal(stopped,true);assert.equal(decoded,false);
});
