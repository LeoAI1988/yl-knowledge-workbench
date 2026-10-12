import React,{useState,useEffect} from 'react';
import {ReactFlow,ReactFlowProvider,Controls,Handle,Position} from '@xyflow/react';
import {ArrowRight,ArrowLeft,Maximize2,Minimize2} from 'lucide-react';

function ReadingNode({data}){return <div className="reading-node"><Handle type="target" position={Position.Left}/><small>{data.center?'正在阅读':'相关内容'}</small><strong>{data.title}</strong><p>{data.quote?.slice(0,44)}</p><Handle type="source" position={Position.Right}/></div>}
const types={reading:ReadingNode};
export default function Explorer({data,domain,setDomain,query,filtered,focus,setFocus,onPick}){
 const[full,setFull]=useState(false),[offset,setOffset]=useState(0);
 useEffect(()=>{setOffset(0)},[focus,domain,query]);
 useEffect(()=>{const esc=e=>{if(e.key==='Escape')setFull(false)};window.addEventListener('keydown',esc);return()=>window.removeEventListener('keydown',esc)},[]);
 const root=data.nodes.find(n=>n.id===focus);
 const ids=root?[...new Set(data.edges.filter(e=>e.source===root.id||e.target===root.id).map(e=>e.source===root.id?e.target:e.source))]:[];
 const relatives=ids.map(id=>data.nodes.find(n=>n.id===id)).filter(Boolean);
 const shown=relatives.slice(offset,offset+2);
 const nodes=root?[{id:root.id,type:'reading',position:{x:0,y:Math.max(0,(shown.length-1)*145)},data:{...root,center:true}},...shown.map((n,i)=>({id:n.id,type:'reading',position:{x:480,y:i*290},data:n}))]:[];
 const edges=shown.map(n=>({id:root.id+'-'+n.id,source:root.id,target:n.id,type:'default',style:{stroke:'#c3997c',strokeWidth:2}}));
 const browse=n=>{setFocus(n.id)};
 return <section className={'explorer '+(full?'is-full':'')}>
  <header className="explorer-head"><div className="explorer-path"><button onClick={()=>{setDomain('all');setFocus(null)}}>全部知识</button>{domain!=='all'&&<><span>／</span><button onClick={()=>setFocus(null)}>{data.domains.find(d=>d.id===domain)?.title}</button></>}{root&&<><span>／</span><span>相关内容</span></>}</div><button className="secondary" onClick={()=>setFull(!full)}>{full?<Minimize2 size={17}/>:<Maximize2 size={17}/>} {full?'退出全屏':'全屏查看'}</button></header>
  {root?<><div className="explorer-intro"><button className="text-btn" onClick={()=>setFocus(null)}><ArrowLeft size={16}/>返回知识列表</button><p>一次看一个观点。点击卡片阅读，更多内容可逐组查看。</p></div><div className="reading-graph"><ReactFlowProvider><ReactFlow key={focus+'-'+offset+'-'+full} nodes={nodes} edges={edges} nodeTypes={types} fitView fitViewOptions={{padding:.12,maxZoom:1}} minZoom={.45} maxZoom={1.5} nodesDraggable={false} onNodeClick={(_,n)=>onPick(n.id)} proOptions={{hideAttribution:true}}><Controls showInteractive={false}/></ReactFlow></ReactFlowProvider></div>{!relatives.length&&<p>这个观点暂时没有相关内容，可以先阅读原文。</p>}{relatives.length>2&&<div className="pager"><button disabled={!offset} onClick={()=>setOffset(offset-2)}>上一组</button><span>{offset+1}–{Math.min(offset+2,relatives.length)} / {relatives.length}</span><button disabled={offset+2>=relatives.length} onClick={()=>setOffset(offset+2)}>下一组</button></div>}</>:domain==='all'&&!query?<><div className="explorer-intro"><h1>你的知识，从这里展开</h1><p>选一个领域，找到观点、原话和可以使用的内容。</p></div><div className="domain-cards">{data.domains.map((d,i)=><button key={d.id} onClick={()=>{setDomain(d.id);setFocus(null)}}><span className="domain-number">0{i+1}</span><h2>{d.title}</h2><p>{d.description}</p><footer><span>{d.count} 个知识点</span><ArrowRight size={20}/></footer></button>)}</div></>:<><div className="explorer-intro"><h2>{query?'搜索结果':data.domains.find(d=>d.id===domain)?.title}</h2><p>{filtered.length} 个知识点 · 点开阅读，或查看相关内容</p></div><div className="browse-list">{filtered.map(n=><article key={n.id}><button className="browse-read" onClick={()=>onPick(n.id)}><h3>{n.title}</h3><p>{(n.quote||n.explanation||'').slice(0,110)}</p></button><button className="text-btn" onClick={()=>browse(n)}>相关内容 <ArrowRight size={16}/></button></article>)}{!filtered.length&&<p className="empty">没有找到，试试更短的关键词。</p>}</div></>}
 </section>
}



