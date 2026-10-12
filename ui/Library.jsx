import React,{useEffect,useMemo,useState} from 'react';
import {ArrowLeft,ArrowUpRight,BookOpen,FileText,Search,LoaderCircle} from 'lucide-react';

export default function Library({mode,setMode,onBack,onWork,onSource,api}){
 const[data,setData]=useState(null),[query,setQuery]=useState(''),[category,setCategory]=useState('全部'),[error,setError]=useState('');
 useEffect(()=>{let live=true;api('/library').then(d=>live&&setData(d)).catch(e=>live&&setError(e.message));return()=>{live=false}},[]);
 const pool=data?.[mode]||[];
 const categoryOf=r=>mode==='works'?(r.platform||'其他作品'):r.category;
 const categories=['全部',...new Set(pool.map(categoryOf))];
 const rows=useMemo(()=>pool.filter(r=>(category==='全部'||categoryOf(r)===category)&&(!query||r.title.toLowerCase().includes(query.toLowerCase()))),[pool,mode,query,category]);
 function switchMode(next){setMode(next);setCategory('全部');setQuery('')}
 return <section className="library-page"><button className="secondary" onClick={onBack}><ArrowLeft size={17}/>返回首页</button><div className="page-heading"><div><h1>{mode==='works'?'全部作品':'原始资料库'}</h1><p>{mode==='works'?'文章、口播与已保存的作品，点开就能阅读。':'回到最初的记录、原话和参考资料。'}</p></div></div>
  <div className="workspace-toolbar"><div className="segmented">{[['works','全部作品',FileText],['sources','原始资料',BookOpen]].map(([id,label,Icon])=><button className={mode===id?'active':''} key={id} onClick={()=>switchMode(id)}><Icon size={16}/>{label}{data&&<span>{data[id].length}</span>}</button>)}</div><label className="search-field"><Search size={16}/><input aria-label="搜索资料库" placeholder="输入标题关键词…" value={query} onChange={e=>setQuery(e.target.value)}/></label></div>
  <nav className="library-filters" aria-label="资料分类">{categories.map(c=><button key={c} className={category===c?'active':''} onClick={()=>setCategory(c)}>{c}</button>)}</nav>
  {error?<p className="error">{error}</p>:!data?<div className="empty"><LoaderCircle className="spin"/>正在整理目录</div>:<><p className="muted">{rows.length} 份{mode==='works'?'作品':'资料'}</p><div className="library-grid">{rows.map(r=><button key={r.id} className="library-card" onClick={()=>mode==='works'?onWork(r.id):onSource(r.id)}><small>{categoryOf(r)}</small><h3>{r.title}</h3><footer><span>{mode==='works'?[r.status,r.date?.slice(0,10)].filter(Boolean).join(' · '):r.changed?'原文已更新':r.node_ids?.length?`${r.node_ids.length} 个关联观点`:'阅读原文'}</span><ArrowUpRight size={17}/></footer></button>)}</div>{!rows.length&&<p className="empty">没有匹配内容，换个关键词试试。</p>}<p className="page-footnote">显示已接入本工作台的本地资料。作品的不同版本分别保留，受限档案不会出现在此处。</p></>}
 </section>
}
