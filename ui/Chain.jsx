import React,{useState,useEffect} from 'react';
import {ArrowLeft} from 'lucide-react';
export default function Chain({detail,topics,onOpen,onBack}){
 const[expanded,setExpanded]=useState(false),[opened,setOpened]=useState({});
 useEffect(()=>{const f=e=>{if(e.key==='Escape')setExpanded(false)};window.addEventListener('keydown',f);return()=>window.removeEventListener('keydown',f)},[]);
 if(!detail)return <section className="reading-chain"><button className="secondary reading-back" onClick={onBack}><ArrowLeft size={17}/>返回上一层</button><p className="empty">正在读取这个知识点…</p></section>;
 const related=topics.filter(t=>t.node_ids.includes(detail.id));
 const groups=[
  ['原文从哪里来',detail.sources.map(s=>({title:s.title,text:s.changed?'原文已更新，需要核对': '阅读完整原文',action:'source',value:s.id,changed:s.changed}))],
  ['可以使用的表达',detail.expressions.map(e=>({title:e.text,text:'',action:'expression',value:e}))],
  ['相关作品',detail.works.map(w=>({title:w.title,text:w.platform,action:'work',value:w}))],
  ['选题与效果',related.map(t=>({title:t.title,text:t.metrics.length?'查看作品表现与成交记录':'查看历史选题',action:'topic',value:t}))]
 ];
 return <section className={'reading-chain '+(expanded?'is-full':'')}><header><button className="secondary reading-back" onClick={onBack}><ArrowLeft size={17}/>返回上一层</button><button className="secondary" onClick={()=>setExpanded(!expanded)}>{expanded?'退出全屏':'全屏阅读'}</button></header><div className="reading-chain-title"><small>围绕这个知识点</small><h2>{detail.title}</h2></div><blockquote>{detail.quote}</blockquote><div className="chain-groups">{groups.map(([title,items],i)=><section key={title}><h3><span>0{i+1}</span>{title} <small>{items.length}</small></h3>{items.length?(opened[title]?items:items.slice(0,3)).map((item,j)=><button key={j} onClick={()=>onOpen(item)}><strong>{item.title}</strong>{item.text&&<p>{item.text}</p>}</button>):<p className="muted">暂时没有相关内容</p>}{items.length>3&&<button className="text-btn" onClick={()=>setOpened({...opened,[title]:!opened[title]})}>{opened[title]?"收起":"查看全部 "+items.length+" 项"}</button>}</section>)}</div></section>
}

