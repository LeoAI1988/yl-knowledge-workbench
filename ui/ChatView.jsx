import React,{useEffect,useRef,useState} from 'react';
import {ArrowUp,ArrowDown,BookOpen,Copy,Check,Link,X,LoaderCircle} from 'lucide-react';
import './chat.css';

export default function ChatView({model="gpt-6-astra",avatar="/avatar.png",name="我的知识助手",messages,question,setQuestion,sendQuestion,job,busy,jobText,context,clearContext,showSource,Markdown,notify}){
 const scroll=useRef(null),input=useRef(null),following=useRef(true);
 const[copied,setCopied]=useState(null),[showLatest,setShowLatest]=useState(false);
 const hasMessages=messages.length>0;
 const jumpToLatest=()=>{const el=scroll.current;if(el){el.scrollTop=el.scrollHeight;following.current=true;setShowLatest(false)}};
 useEffect(()=>{if(following.current)jumpToLatest()},[messages,jobText,busy]);
 useEffect(()=>{const el=input.current;if(el){el.style.height='auto';el.style.height=Math.min(el.scrollHeight,180)+'px'}},[question]);
 async function copyReply(text,index){try{await navigator.clipboard.writeText(text);setCopied(index);setTimeout(()=>setCopied(null),1800)}catch{notify('复制未成功，请选择文字复制')}}
 function submit(){if(job||!question.trim())return;following.current=true;sendQuestion();input.current?.focus()}
 const composer=<div className="conversation-input-area"><div className="conversation-composer">
   {context&&<div className="conversation-context"><Link size={14}/><span>{context}</span><button aria-label="移除带入的观点" onClick={clearContext}><X size={14}/></button></div>}
   <textarea ref={input} rows={2} aria-label="向分身提问" placeholder={hasMessages?'继续聊聊…':'你想从哪里开始？'} value={question} onChange={e=>setQuestion(e.target.value)} onKeyDown={e=>{if(e.key==='Enter'&&!e.shiftKey&&!e.nativeEvent.isComposing){e.preventDefault();submit()}}}/>
   <div className="conversation-input-tools"><span className="conversation-library"><BookOpen size={16}/>我的知识库</span><div className="conversation-model">{model==='gpt-6-astra'?'GPT-6 Astra':model}</div><button className="primary conversation-send" aria-label="发送问题" title="发送问题" disabled={!!job||!question.trim()} onClick={submit}>{job?<LoaderCircle size={19} className="spin"/>:<ArrowUp size={21}/>}</button></div>
  </div><p className="conversation-input-hint">Enter 发送 · Shift + Enter 换行</p></div>;
 return <section className={'conversation '+(hasMessages?'has-messages':'is-empty')} aria-label={name+"对话"}>
  {hasMessages&&<header className="conversation-identity"><img src={avatar} alt={name}/><div><h1>{name}</h1><p>和我的知识聊一聊</p></div></header>}
  {hasMessages?<><div className="conversation-scroll" ref={scroll} onScroll={()=>{const el=scroll.current;const atEnd=el.scrollHeight-el.scrollTop-el.clientHeight<100;following.current=atEnd;setShowLatest(!atEnd)}}><div className="conversation-column" role="log" aria-label="对话记录" aria-live="polite" aria-relevant="additions">
    {messages.map((m,i)=><article className={'conversation-message '+m.role} aria-label={m.role==='user'?'我的提问':name+'的回答'} key={i}>
      {m.role!=='user'&&<img className="conversation-avatar" src={avatar} alt={name}/>}
      <div className="conversation-message-body"><Markdown text={m.text}/>
      {m.citations?.length>0&&<details className="conversation-sources"><summary><BookOpen size={15}/>参考了 {m.citations.length} 段原文</summary><div>{m.citations.map(c=><button key={c.citation} onClick={()=>showSource(c.source_id)}><b>{c.title}</b><span>{c.text.slice(0,160)}</span><small>{c.quote_ready?'本人原文':'查看来源与上下文'}</small></button>)}</div></details>}
      {m.role!=='user'&&<div className="conversation-message-tools"><button aria-label="复制回答" title="复制回答" onClick={()=>copyReply(m.text,i)}>{copied===i?<Check size={16}/>:<Copy size={16}/>}</button></div>}
      </div></article>)}
    {job&&<article className="conversation-message assistant"><img className="conversation-avatar" src={avatar} alt={name}/><div className="conversation-message-body"><div className="conversation-progress" role="status"><LoaderCircle size={15} className="spin"/>{busy||'正在思考…'}</div>{jobText&&<Markdown text={jobText}/>}</div></article>}
   </div></div>{showLatest&&<button className="conversation-latest" onClick={jumpToLatest} aria-label="回到最新消息"><ArrowDown size={17}/></button>}{composer}</>:<div className="conversation-welcome"><div className="conversation-greeting"><img src={avatar} alt=""/><h1>{name}</h1></div><p className="conversation-intro">今天，想聊些什么？</p>{composer}<div className="conversation-starters">{[['找回一个观点','在我的笔记里，有哪些值得重新思考的观点？'],['讨论经营问题','我关于公司经营，有哪些看起来相反但需要同时考虑的观点？'],['寻找创作灵感','如何把我的知识体系用到内容创作中？']].map(([label,q])=><button key={label} onClick={()=>{setQuestion(q);input.current?.focus()}}>{label}</button>)}</div></div>}
 </section>
}
