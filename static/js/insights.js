'use strict';
(() => {
  const source = document.getElementById('learning-analytics');
  if (!source) return;
  let data;
  try { data = JSON.parse(source.textContent); } catch { return; }
  const NS = 'http://www.w3.org/2000/svg';
  const $ = id => document.getElementById(id);
  const node = (tag, cls, text) => {
    const el = document.createElement(tag);
    if (cls) el.className = cls;
    if (text !== undefined) el.textContent = text;
    return el;
  };
  const svgNode = (tag, attrs = {}, text) => {
    const el = document.createElementNS(NS, tag);
    Object.entries(attrs).forEach(([key, value]) => el.setAttribute(key, String(value)));
    if (text !== undefined) el.textContent = text;
    return el;
  };
  const hosts = Object.fromEntries([...document.querySelectorAll('[data-chart]')]
    .filter(el => ['memory','rating-matrix','workload','relationships'].includes(el.dataset.chart))
    .map(el => [el.dataset.chart, el]));
  const empty = (host, text) => host.append(node('p', 'chart-empty', text));
  const link = (text, href) => { const a = node('a', '', text); a.href = href; return a; };
  let mode = 'theory';

  function teachingCurve(span, stability, reviewed) {
    let last = 0, strength = stability;
    const result = [], reviews = [1,3,7,14];
    for (let step = 0; step <= span*4; step++) {
      const day = step/4;
      const value = 100*Math.exp(-(day-last)/strength);
      result.push({day, value});
      if (reviewed && reviews.includes(day)) {
        last = day;
        strength *= 1.8;
        result.push({day, value:100});
      }
    }
    return result;
  }
  function legendItem(label, colour, dashed = false) {
    const item = node('span'), swatch = node('i');
    swatch.style.borderTop = `3px ${dashed?'dashed':'solid'} ${colour}`;
    item.append(swatch, document.createTextNode(label));
    return item;
  }
  function drawMemory() {
    const host = hosts.memory;
    if (!host) return;
    host.replaceChildren(); $('memory-legend').replaceChildren();
    const span = Number($('memory-horizon').value);
    const width = Math.max(230, Math.floor(host.clientWidth)), height = 310;
    const left = 43, right = 19, top = 30, bottom = 37;
    const w = width-left-right, h = height-top-bottom;
    const x = day => left+w*day/span, y = value => top+h*(1-value/100);
    const svg = svgNode('svg', {viewBox:`0 0 ${width} ${height}`, role:'group', 'aria-label':mode==='theory'?'遗忘与间隔复习教学示意':'从今天起不再复习时的FSRS回忆概率预测'});
    [0,25,50,75,100].forEach(value => {
      svg.append(svgNode('line', {x1:left, y1:y(value), x2:width-right, y2:y(value), stroke:'#e1e7db', 'stroke-dasharray':'3 5'}));
      svg.append(svgNode('text', {x:left-9, y:y(value)+4, 'text-anchor':'end', class:'memory-axis'}, value+'%'));
    });
    const ticks = width<420?[0,span/2,span]:span===14?(width<800?[0,3,7,10,14]:[0,1,3,7,10,14]):[0,3,7,14,21,30];
    ticks.forEach(day => svg.append(svgNode('text', {x:x(day), y:height-12,
      'text-anchor':day===0?'start':day===span?'end':'middle', class:'memory-axis'}, day===0&&mode==='fsrs'?'今天':`第${day}天`)));
    let series;
    if (mode==='theory') {
      const stability = Number($('memory-speed').value);
      series = [
        {name:'一次学习后不复习（示意）', colour:'#bb8a76', points:teachingCurve(span,stability,false)},
        {name:'按示意节点复习', colour:'#3e7059', points:teachingCurve(span,stability,true)},
      ];
      [1,3,7,14].filter(day=>day<=span).forEach(day => {
        svg.append(svgNode('line', {x1:x(day),y1:top,x2:x(day),y2:top+h,stroke:'#aebda4','stroke-dasharray':'3 6'}));
        if (width>=650) svg.append(svgNode('text', {x:x(day)+4,y:18,class:'memory-axis'},`复习${day}`));
      });
      $('memory-caption').textContent = '教学模型 · 非个人测量';
      $('memory-detail').textContent = '复习节点：第1、3、7、14天';
    } else {
      const card = data.memory.cards.find(item=>String(item.id)===$('memory-question').value);
      if (!card) {
        $('memory-caption').textContent = '暂无可用状态，完成复习后建立预测。';
        $('memory-detail').textContent = '';
        empty(host,'暂无符合来源的FSRS状态');
        return;
      }
      series = [{name:'假设未来不再复习：FSRS预测', colour:'#3e7059', points:card.points.filter(p=>p.day<=span)}];
      svg.append(svgNode('line',{x1:left,y1:y(90),x2:width-right,y2:y(90),stroke:'#b48347','stroke-dasharray':'5 4'}));
      $('memory-legend').append(legendItem('90%目标参考线','#b48347',true));
      $('memory-caption').textContent = `${card.example?'含练习记录 · ':''}${card.course} / ${card.title} · 模型预测`;
      $('memory-detail').textContent = `当前预测 ${card.current}% · 稳定性 ${card.stability} 天 · 难度 ${card.difficulty}/10 · 当前复习安排 ${card.due_date}。${data.memory.invalid_count?'另有状态无法用于预测，已排除。':''}`;
    }
    series.forEach(item => {
      svg.append(svgNode('polyline',{points:item.points.map(p=>`${x(p.day)},${y(p.value)}`).join(' '),fill:'none',stroke:item.colour,'stroke-width':2.8,'stroke-linejoin':'round'}));
      item.points.filter(p=>[0,1,3,7,14,21,30].includes(p.day)).forEach(p => {
        const circle = svgNode('circle',{cx:x(p.day),cy:y(p.value),r:3.5,fill:'#fffefa',stroke:item.colour,'stroke-width':2,tabindex:'0',role:'img','aria-label':`${item.name}，第${p.day}天，${p.value.toFixed(1)}%`});
        circle.append(svgNode('title',{},`${item.name} · 第${p.day}天：${p.value.toFixed(1)}%`));
        svg.append(circle);
      });
      $('memory-legend').append(legendItem(item.name,item.colour));
    });
    host.append(svg);
  }
  function drawRatingMatrix() {
    const host = hosts['rating-matrix']; if (!host) return;
    host.replaceChildren();
    if (!data.rating_matrix.length) { empty(host,'暂无活跃课程'); return; }
    const table = node('table','rating-matrix'), head = node('thead'), header = node('tr');
    ['课程','需再练习','答对但费力','独立答对','合计'].forEach(label=>header.append(node('th','',label)));
    head.append(header); table.append(head);
    const body = node('tbody'), palettes = [[173,107,81],[177,148,83],[66,112,82]];
    data.rating_matrix.forEach(row=>{
      const tr = node('tr'), title = node('th'); title.scope='row';
      title.append(link(row.name,`/courses/${row.id}/`)); tr.append(title);
      const total = row.counts.reduce((sum,n)=>sum+n,0);
      row.counts.forEach((count,index)=>{
        const td = node('td','matrix-value',String(count)), share = total?count/total:0;
        td.style.background=count?`rgba(${palettes[index].join(',')},${.13+share*.64})`:'#f5f7f0';
        td.style.color=share>.65?'#fff':'#3d503a';
        td.title=`${row.name}：${['需再练习','独立作答较费力','独立作答较熟练'][index]} ${count}次，占本课程${total?Math.round(share*100):0}%`;
        tr.append(td);
      });
      tr.append(node('td','matrix-total',String(total))); body.append(tr);
    });
    table.append(body); host.append(table);
  }
  function drawWorkload() {
    const host = hosts.workload; if (!host) return;
    host.replaceChildren();
    if (!data.workload.courses.length) { empty(host,'暂无活跃课程'); return; }
    const table=node('table','workload-matrix'), head=node('thead'), header=node('tr');
    header.append(node('th','','课程'));
    data.workload.dates.forEach(day=>{const th=node('th','',day.label); th.title=day.date;header.append(th);});
    head.append(header);table.append(head); const body=node('tbody');
    const max=Math.max(1,...data.workload.courses.flatMap(row=>row.days.map(day=>day.tasks+day.questions)));
    data.workload.courses.forEach(row=>{
      const tr=node('tr'), title=node('th');title.scope='row';title.append(link(row.name,`/courses/${row.id}/`));tr.append(title);
      row.days.forEach((day,index)=>{
        const count=day.tasks+day.questions, td=node('td'), button=node('button','load-cell',String(count));button.type='button';
        const text=`${data.workload.dates[index].date} · ${row.name}：${day.tasks}项未完成任务，${day.questions}道待复习错题`;
        button.title=text;button.setAttribute('aria-label',text);
        button.style.background=count?`rgba(75,117,81,${.12+.72*count/max})`:'#f4f6ef';button.style.color=count/max>.65?'white':'#506747';
        button.addEventListener('click',()=>{
          document.querySelectorAll('.load-cell[aria-pressed]').forEach(el=>el.removeAttribute('aria-pressed'));
          button.setAttribute('aria-pressed','true');
          const focus=$('workload-focus');focus.replaceChildren(node('span','',text+'。 '),
            link('查看该课程未完成任务',`/tasks/?course=${row.id}&status=todo`),document.createTextNode(' · '),link('查看课程错题',`/questions/?course=${row.id}`));
        });td.append(button);tr.append(td);
      });body.append(tr);
    });table.append(body);host.append(table);
  }
  function drawRelationships() {
    const host=hosts.relationships;if(!host)return;host.replaceChildren();
    const course=data.relationships.find(row=>String(row.id)===$('relationship-course').value);
    if(!course){empty(host,'新建课程与知识点后，这里会显示关联。');return;}
    const width=Math.max(700,Math.floor(host.clientWidth)), height=Math.max(310,Math.max(course.points.length,course.questions.length)*80+70);
    const svg=svgNode('svg',{viewBox:`0 0 ${width} ${height}`,width,height,role:'group','aria-label':`${course.name}的知识点与错题关联`});
    const defs=svgNode('defs'), marker=svgNode('marker',{id:'knowledge-arrow',viewBox:'0 0 10 10',refX:9,refY:5,markerWidth:5,markerHeight:5,orient:'auto'});
    marker.append(svgNode('path',{d:'M 0 0 L 10 5 L 0 10 z',fill:'#99b08b'}));defs.append(marker);svg.append(defs);
    const boxW=172, boxH=62, rootX=24, midX=(width-boxW)/2, lastX=width-boxW-24;
    const positions=(items,x)=>items.map((item,index)=>({...item,x,y:47+(height-85)/Math.max(1,items.length)*(index+.5)-boxH/2}));
    const root={id:course.id,name:course.name,x:rootX,y:height/2-boxH/2}, points=positions(course.points,midX), questions=positions(course.questions,lastX);
    const edge=(from,to,dashed=false)=>{
      const x1=from.x+boxW,y1=from.y+boxH/2,x2=to.x,y2=to.y+boxH/2;
      svg.append(svgNode('path',{d:`M${x1},${y1} C${(x1+x2)/2},${y1} ${(x1+x2)/2},${y2} ${x2},${y2}`,fill:'none',stroke:'#b0c0a5','stroke-width':1.6,'stroke-dasharray':dashed?'4 4':'none','marker-end':'url(#knowledge-arrow)'}));
    };
    points.forEach(point=>edge(root,point));
    questions.forEach(question=>{
      const parents=points.filter(p=>question.point_ids.includes(p.id));
      if(parents.length)parents.forEach(point=>edge(point,question));else edge(root,question,true);
    });
    function box(item,type,href,colour){
      const a=svgNode('a',{href,'aria-label':`${type}：${item.name||item.title}`});
      a.append(svgNode('rect',{x:item.x,y:item.y,width:boxW,height:boxH,rx:10,fill:colour,stroke:'#d9e2d3'}));
      a.append(svgNode('text',{x:item.x+12,y:item.y+18,class:'graph-type'},type));
      const text=item.name||item.title;
      const label=svgNode('foreignObject',{x:item.x+12,y:item.y+25,width:boxW-24,height:34});
      const content=document.createElementNS('http://www.w3.org/1999/xhtml','div');content.setAttribute('class','graph-label-text');content.textContent=text;label.append(content);a.append(label);
      a.append(svgNode('title',{},text));svg.append(a);
    }
    [[rootX,'课程'],[midX,'知识点'],[lastX,'错题']].forEach(([x,label])=>svg.append(svgNode('text',{x:x+10,y:21,class:'graph-column'},label)));
    box(root,'课程',`/courses/${course.id}/`,'#eaf1e5');points.forEach(p=>box(p,'知识点',`/questions/?point=${p.id}`,'#f2f5eb'));questions.forEach(q=>box(q,'错题',`/questions/${q.id}/`,'#fffaf1'));
    host.append(svg);
  }

  if ($('memory-question')) data.memory.cards.forEach(card=>{
    const option=node('option','',`${card.example?'':''}${card.course} · ${card.title}`);option.value=String(card.id);$('memory-question').append(option);
  });
  if ($('relationship-course')) data.relationships.forEach(course=>{
    const option=node('option','',course.name);option.value=String(course.id);$('relationship-course').append(option);
  });
  document.querySelectorAll('[data-memory-mode]').forEach(button=>button.addEventListener('click',()=>{
    mode=button.dataset.memoryMode;document.querySelectorAll('[data-memory-mode]').forEach(el=>el.setAttribute('aria-pressed',String(el===button)));
    $('theory-control').hidden=mode!=='theory';$('fsrs-control').hidden=mode!=='fsrs';$('memory-risks').hidden=mode!=='fsrs';drawMemory();
  }));
  ['memory-speed','memory-horizon','memory-question'].forEach(id=>$(id)?.addEventListener('change',drawMemory));
  $('relationship-course')?.addEventListener('change',drawRelationships);
  function render(){drawMemory();drawRatingMatrix();drawWorkload();drawRelationships();}
  render();
  if(typeof ResizeObserver==='function'){
    const widths=new WeakMap();let frame;
    const observer=new ResizeObserver(entries=>{
      let changed=false;entries.forEach(entry=>{const width=Math.floor(entry.contentRect.width);if(widths.get(entry.target)!==width){widths.set(entry.target,width);changed=true;}});
      if(changed){cancelAnimationFrame(frame);frame=requestAnimationFrame(render);}
    });Object.values(hosts).forEach(host=>observer.observe(host));
  }
})();
