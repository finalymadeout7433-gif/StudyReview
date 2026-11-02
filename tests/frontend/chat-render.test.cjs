const {test}=require('node:test'),assert=require('node:assert/strict'),vm=require('node:vm'),fs=require('node:fs');
class Element{
  constructor(tag){this.tagName=tag;this.children=[];this._text='';}
  append(...items){this.children.push(...items);}
  get firstChild(){return this.children[0];}
  set textContent(value){this._text=String(value);this.children=[];}
  get textContent(){return this._text+this.children.map(child=>child.textContent).join('');}
  set innerHTML(_){throw Error('HTML injection is forbidden');}
}
const document={createElement:tag=>new Element(tag),createTextNode:value=>({textContent:value}),getElementById:()=>null},window={};
vm.runInNewContext(fs.readFileSync(require.resolve('../../static/js/chat-widgets.js'),'utf8'),{document,window});
const tags=root=>[root.tagName,...root.children.flatMap(child=>child.children?tags(child):[])];
test('AI markup stays text while headings, lists and code are readable',()=>{
  const root=window.StudyChat.richText('# 主键\n\n- **唯一**\n- `NOT NULL`\n\n<script>alert(1)</script>\n```sql\nSELECT * FROM t;\n```');
  assert.ok(tags(root).includes('h4'));assert.ok(tags(root).includes('ul'));assert.ok(tags(root).includes('strong'));assert.ok(tags(root).includes('pre'));
  assert.ok(!tags(root).includes('script'));assert.match(root.textContent,/<script>alert\(1\)<\/script>/);assert.match(root.textContent,/SELECT \* FROM t;/);
});
test('incomplete fenced code and line breaks retain question content',()=>{
  const root=window.StudyChat.richText('第一行\n第二行\n\n```python\nprint("<img>")');
  assert.match(root.textContent,/第一行\n第二行/);assert.match(root.textContent,/<img>/);assert.ok(!tags(root).includes('img'));
});
