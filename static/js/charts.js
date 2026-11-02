'use strict';
// Offline SVG/DOM charts. Labels use textContent, never HTML from user data.
(() => {
  const source = document.getElementById('learning-analytics'); if (!source) return;
  let data; try { data = JSON.parse(source.textContent); } catch { return; }
  const NS = 'http://www.w3.org/2000/svg';
  const colours = {green:'#628266', pale:'#d1dcbc', red:'#c88a74', grid:'#edf0e7', muted:'#9aa68c'};
  const element = (tag, cls, text) => { const node=document.createElement(tag); if(cls)node.className=cls; if(text!==undefined)node.textContent=text; return node; };
  const svgNode = (tag, attrs={}, text) => { const node=document.createElementNS(NS,tag); Object.entries(attrs).forEach(([key,value])=>node.setAttribute(key,String(value))); if(text!==undefined)node.textContent=text; return node; };
  const empty = (host,text) => host.append(element('div','chart-empty',text));
  function plot(host, rows, bars=false) {
    const width=Math.max(230,Math.floor(host.clientWidth)), height=220;
    const left=29,right=14,top=21,bottom=31, w=width-left-right,h=height-top-bottom;
    const maxCount=Math.max(1,...rows.map(row=>row.count)), step=Math.max(1,Math.ceil(maxCount/3)), ceiling=step*3;
    const svg=svgNode('svg',{viewBox:`0 0 ${width} ${height}`,role:'group','aria-label':bars?'未来七天待复习错题数量':'所选时间范围内的复习次数'});
    for(let i=0;i<=3;i++){
      const y=top+h-h*i/3;
      svg.append(svgNode('line',{x1:left,y1:y,x2:width-right,y2:y,stroke:colours.grid,'stroke-dasharray':i?'3 5':'none'}));
      svg.append(svgNode('text',{x:left-9,y:y+3,'text-anchor':'end','class':'axis-label'},String(i*step)));
    }
    const x=index=>bars?left+w*(index+.5)/rows.length:left+w*(rows.length===1?.5:index/(rows.length-1));
    const y=count=>top+h-h*count/ceiling;
    if(!bars && rows.length){
      const points=rows.map((row,index)=>`${x(index)},${y(row.count)}`).join(' ');
      svg.append(svgNode('polygon',{points:`${x(0)},${top+h} ${points} ${x(rows.length-1)},${top+h}`,fill:'#edf3e7'}));
      svg.append(svgNode('polyline',{points,fill:'none',stroke:colours.green,'stroke-width':2.3,'stroke-linecap':'round','stroke-linejoin':'round'}));
    }
    rows.forEach((row,index)=>{
      const description=`${row.date}${row.end&&row.end!==row.date?' 至 '+row.end:''}：${row.count}${bars?' 道待复习错题':' 次复习'}`;
      let mark;
      if(bars){
        const bw=Math.min(28,w/rows.length*.46), bh=h*row.count/ceiling;
        mark=svgNode('rect',{x:x(index)-bw/2,y:y(row.count),width:bw,height:Math.max(row.count?3:1,bh),rx:4,fill:index===0?colours.green:'#b9cba5'});
        svg.append(svgNode('text',{x:x(index),y:y(row.count)-9,'text-anchor':'middle','class':'chart-value'},String(row.count)));
      } else {
        mark=svgNode('circle',{cx:x(index),cy:y(row.count),r:rows.length>20?2.5:3.5,fill:'#fffefa',stroke:colours.green,'stroke-width':1.7});
      }
      mark.setAttribute('tabindex','0'); mark.setAttribute('role','img'); mark.setAttribute('aria-label',description);
      mark.append(svgNode('title',{},description)); svg.append(mark);
    });
    const indexes=bars?rows.map((_,i)=>i).filter(i=>width>=340||i%2===0):[...new Set([0,Math.floor((rows.length-1)/3),Math.floor((rows.length-1)*2/3),rows.length-1])];
    indexes.forEach(index=>{if(index>=0&&rows[index])svg.append(svgNode('text',{x:x(index),y:height-9,'text-anchor':index===0&&!bars?'start':index===rows.length-1&&!bars?'end':'middle','class':'axis-label'},rows[index].label));});
    if(!rows.some(row=>row.count>0))svg.append(svgNode('text',{x:left+w/2,y:top+h*.42,'text-anchor':'middle'},bars?'这7天暂未安排复习':'这段时间还没有复习记录'));
    host.append(svg);
  }
  function donut(host) {
    const total=data.ratings.reduce((n,row)=>n+row.count,0), palette=[colours.red,colours.pale,colours.green];
    const ring=element('div','donut-ring'), svg=svgNode('svg',{viewBox:'0 0 144 144','aria-hidden':'true'});
    const radius=54,circumference=Math.PI*2*radius; let offset=0;
    svg.append(svgNode('circle',{cx:72,cy:72,r:radius,fill:'none',stroke:'#edf1e6','stroke-width':13}));
    data.ratings.forEach((row,index)=>{
      if(!total||!row.count)return;
      const length=row.count/total*circumference;
      const circle=svgNode('circle',{cx:72,cy:72,r:radius,fill:'none',stroke:palette[index],'stroke-width':13,'stroke-dasharray':`${length} ${circumference-length}`,'stroke-dashoffset':-offset,transform:'rotate(-90 72 72)'});
      circle.append(svgNode('title',{},`${row.name}：${row.count}次`));svg.append(circle);offset+=length;
    });
    ring.append(svg);const centre=element('div','donut-centre');centre.append(element('strong','',String(total)),element('small','','次复习'));ring.append(centre);host.append(ring);
    const legend=element('div','donut-legend');
    data.ratings.forEach((row,index)=>{const item=element('div'),swatch=element('i','swatch');swatch.style.background=palette[index];item.append(swatch,element('span','',row.name),element('b','',`${row.count} · ${total?Math.round(row.count/total*100):0}%`));legend.append(item);});
    host.append(legend);host.setAttribute('aria-label',`复习自评分布，共${total}次；`+data.ratings.map(row=>`${row.name}${row.count}次`).join('，'));
  }
  function progress(host, points=false) {
    const rows=points?data.points:data.courses;
    if(!rows.length){empty(host,points?'还没有关联知识点的活跃错题':'还没有活跃课程');return;}
    const max=Math.max(1,...rows.map(row=>points?row.count:row.total));
    rows.forEach(row=>{
      const link=element('a','chart-bar-row');
      link.href=points?`/questions/?point=${encodeURIComponent(row.id)}`:`/tasks/?course=${encodeURIComponent(row.id)}`;
      const title=element('div','chart-bar-title');title.append(element('span','',row.name),element('b','',points?`${row.count} 题`:`${row.done} / ${row.total} 项完成`));
      const track=element('div','chart-track');
      const values=points?[[row.count,colours.green]]:[[row.done,colours.green],[row.pending,colours.pale],[row.overdue,colours.red]];
      values.forEach(([count,colour])=>{const bar=element('i');bar.style.width=(count/max*100)+'%';bar.style.background=colour;track.append(bar);});
      link.title=points?`${row.name}：${row.count}道关联错题`:`${row.name}：已完成${row.done}项，未逾期${row.pending}项，逾期${row.overdue}项`;
      link.append(title,track);host.append(link);
    });
  }
  function heatmap(host) {
    const rows=data.heatmap;if(!rows.length)return;
    const grid=element('div','heatmap-grid'), leading=(new Date(rows[0].date+'T00:00:00Z').getUTCDay()+6)%7;
    const columns=Math.ceil((leading+rows.length)/7), size=Math.min(17,Math.floor((host.clientWidth-32-(columns-1)*4)/columns));
    const calendar=element('div','heatmap-calendar'), weekdays=element('div','heatmap-weekdays');
    ['一','二','三','四','五','六','日'].forEach(day=>weekdays.append(element('span','',day)));
    weekdays.style.gridTemplateRows=`repeat(7,${size}px)`;
    const monthLabels=element('div','heatmap-dates');monthLabels.style.gridTemplateColumns=`repeat(${columns},${size}px)`;
    for(let col=0;col<columns;col++){
      const row=rows[Math.max(0,col*7-leading)], label=element('span','',row&&(col===0||col>=3&&row.date.slice(5,7)!==rows[Math.max(0,(col-1)*7-leading)].date.slice(5,7))?row.date.slice(5).replace('-','/'): '');
      monthLabels.append(label);
    }
    grid.style.gridTemplateRows=`repeat(7,${size}px)`;grid.style.gridAutoColumns=size+'px';grid.style.gap='4px';
    for(let i=0;i<leading;i++){const blank=element('span');blank.style.visibility='hidden';grid.append(blank);}
    const max=Math.max(1,...rows.map(row=>row.count));
    rows.forEach(row=>{const cell=element('span','heatmap-cell');cell.dataset.level=String(row.count?Math.max(1,Math.ceil(row.count/max*4)):0);cell.title=`${row.date}：${row.count}次复习`;grid.append(cell);});calendar.append(monthLabels,weekdays,grid);host.append(calendar);
    host.setAttribute('aria-label',`${rows[0].date}至${rows[rows.length-1].date}的复习活动；${rows.filter(row=>row.count>0).length}天有复习记录。`);
  }
  const hosts=[...document.querySelectorAll('[data-chart]')].filter(host=>['trend','ratings','courses','points','upcoming','heatmap'].includes(host.dataset.chart));
  function render(){hosts.forEach(host=>{host.replaceChildren();try{switch(host.dataset.chart){case 'trend':plot(host,data.trend);break;case 'ratings':donut(host);break;case 'courses':progress(host);break;case 'points':progress(host,true);break;case 'upcoming':plot(host,data.upcoming,true);break;case 'heatmap':heatmap(host);break;}}catch{empty(host,'图表暂时无法显示，可查看数据明细。');}});}
  let frame;function schedule(){cancelAnimationFrame(frame);frame=requestAnimationFrame(render);}
  render(); if(typeof ResizeObserver==='function'){const widths=new WeakMap();const observer=new ResizeObserver(entries=>{let changed=false;entries.forEach(entry=>{const width=Math.floor(entry.contentRect.width);if(widths.get(entry.target)!==width){widths.set(entry.target,width);changed=true;}});if(changed)schedule();});hosts.forEach(host=>observer.observe(host));}else{window.addEventListener('resize',schedule);}
})();
