import React,{useMemo,useState} from 'react';
export default function KnowledgeGroups({nodes,edges,onPick}){
 const[all,setAll]=useState(false);
 const {groups,loose}=useMemo(()=>{
  const byId=new Map(nodes.map(n=>[n.id,n]));
  const centers=nodes.filter(n=>['观点','概念','论述链'].includes(n.kind));
  const covered=new Set();
  const groups=centers.map(n=>{const related=edges.filter(e=>e.source===n.id||e.target===n.id).map(e=>({...e,node:byId.get(e.source===n.id?e.target:e.source)})).filter(e=>e.node);if(related.length){covered.add(n.id);related.forEach(r=>covered.add(r.node.id))}return {node:n,related}}).filter(g=>g.related.length);
  return {groups,loose:nodes.filter(n=>!covered.has(n.id))};
 },[nodes,edges]);
 const card=n=><button className="knowledge-card" key={n.id} onClick={()=>onPick(n.id)}><span className="pill">{n.kind}</span><h3>{n.title}</h3><p>{(n.quote||n.explanation||'').slice(0,135)}</p></button>;
 return <section className="knowledge-groups"><header className="section-title"><div><h2>{all?'全部知识条目':'围绕一个观点阅读'}</h2><p>点开主观点，继续看与它相关的案例、方法和表达。</p></div><button className="text-btn" onClick={()=>setAll(!all)}>{all?'按观点组织':'查看全部条目'}</button></header>{all?<div className="card-grid">{nodes.map(card)}</div>:<><div className="group-grid">{groups.map(({node,related})=><article className="thought-group" key={node.id}><button className="group-center" onClick={()=>onPick(node.id)}><small>从这个{node.kind==='论述链'?'完整思考':'观点'}出发</small><h3>{node.title}</h3><p>{(node.quote||node.explanation||'').slice(0,120)}</p></button><details><summary>{related.length} 项相关内容 · 展开阅读</summary>{related.map(r=><div className="group-relation" key={r.id}><button onClick={()=>onPick(r.node.id)}><span>{r.node.kind}</span>{r.node.title}</button>{r.evidence&&<details><summary>为什么相关</summary><p>{r.evidence}</p></details>}</div>)}</details></article>)}</div>{loose.length>0&&<><h3 className="loose-heading">还可以单独阅读 <small>{loose.length} 项</small></h3><p className="muted">这些内容尚未与当前板块的主观点建立明确联系。</p><div className="card-grid">{loose.map(card)}</div></>}{!nodes.length&&<div className="empty">没有匹配内容，可以换个关键词或切回全部。</div>}</>}</section>
}
