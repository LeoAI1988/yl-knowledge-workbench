import React,{useEffect,useRef,useState} from 'react';

export default function BoardMaterials({api}){
  const [mode,setMode]=useState('closed'), [kind,setKind]=useState('idea');
  const [query,setQuery]=useState(''),[found,setFound]=useState([]),[more,setMore]=useState(false);
  const [picked,setPicked]=useState([]),[draft,setDraft]=useState(null),[message,setMessage]=useState('');
  const [busy,setBusy]=useState(false),[selection,setSelection]=useState(null);
  const opened=useRef("");
  const call=(action,fields={})=>api('/desktop-board',{action,...fields});
  function showDraft(value){
    const unsaved=sessionStorage.getItem('board-edit-'+value.id);
    if(unsaved){
      const cache=JSON.parse(unsaved);
      if(cache.revision===value.revision)value={...value,title:cache.title,body:cache.body,coverage:cache.coverage||value.coverage||{}};
    }
    setDraft(value);setMode('edit');
    history.replaceState(null,'','#board-work='+value.id);
  }
  useEffect(()=>{
    let mounted=true;
    function receive(){
      const route=location.hash;
      const m=/^#(board|board-work)=([a-f0-9]{32})$/.exec(route);
      if(!m||opened.current===route)return;
      opened.current=route;setMessage('');setSelection(null);setMode('pick');
      call(m[1]==='board'?'redeem':'read',m[1]==='board'?{ticket:m[2]}:{work:m[2]})
        .then(value=>{if(mounted&&opened.current===route)showDraft(value)})
        .catch(e=>{if(mounted&&opened.current===route)setMessage(e.message)});
    }
    receive();window.addEventListener('hashchange',receive);
    return ()=>{mounted=false;window.removeEventListener('hashchange',receive)};
  },[]);
  useEffect(()=>{
    if(mode!=='pick')return;
    let active=true;
    const timer=setTimeout(()=>call('list',{type:kind,query}).then(r=>{
      if(active){setFound(r.items);setMore(r.more)}
    }).catch(e=>{if(active)setMessage(e.message)}),120);
    return ()=>{active=false;clearTimeout(timer)};
  },[mode,kind,query]);
  const toggle=(r)=>setPicked(p=>p.some(x=>x.type===r.type&&x.id===r.id)?p.filter(x=>x.type!==r.type||x.id!==r.id):[...p,r]);
  function edit(key,value){
    const next={...draft,[key]:value};setDraft(next);
    sessionStorage.setItem('board-edit-'+next.id,JSON.stringify({revision:next.revision,title:next.title,body:next.body,coverage:next.coverage}));
  }
  async function action(fn){
    setBusy(true);setMessage('');
    try { await fn() }catch(e){setMessage(e.message)}finally{setBusy(false)}
  }
  async function save(stage){
    const saved=await call('save',{work:draft.id,title:draft.title,body:draft.body,coverage:draft.coverage,revision:draft.revision,stage});
    sessionStorage.removeItem('board-edit-'+draft.id);
    setDraft({...draft,...saved});setMessage(stage==='final'?'已定稿，提示板已更新':'草稿已保存');
  }
  if(mode==='closed')return <button className="secondary" onClick={()=>setMode('pick')}>从桌面提示板选材</button>;
  return <section style={{padding:'16px 20px',margin:'12px 0',border:'1px solid #dfd9cf',borderRadius:10,background:'#fffdfa'}}>
    <header style={{display:'flex',alignItems:'center',justifyContent:'space-between'}}><h3>{mode==='edit'?'提示板写作':'从桌面提示板选材'}</h3>
      <button className="secondary" onClick={()=>{history.replaceState(null,'',location.pathname);setMode('closed')}}>收起</button></header>
    {mode==='pick'&&<><div style={{display:'flex',gap:8,marginBlock:10}}>
      <select value={kind} onChange={e=>setKind(e.target.value)}><option value="idea">碎片灵感</option><option value="post">过往选题</option></select>
      <input aria-label="筛选材料" placeholder="筛选材料" value={query} onChange={e=>setQuery(e.target.value)}/></div>
      <div style={{maxHeight:240,overflow:'auto'}}>{found.map(r=><label key={r.type+r.id} style={{display:'flex',alignItems:'center',gap:8,padding:'4px 0'}}>
        <input type="checkbox" checked={picked.some(x=>x.id===r.id&&x.type===r.type)} onChange={()=>toggle(r)}/>{r.title}</label>)}</div>
      {more&&<button className="secondary" disabled={busy} onClick={()=>action(async()=>{const r=await call('list',{type:kind,query,offset:found.length});setFound([...found,...r.items]);setMore(r.more)})}>更多材料</button>}
      <button className="primary" disabled={!picked.length||busy} onClick={()=>action(async()=>showDraft(await call('open',{refs:picked.map(({type,id})=>({type,id}))})))}>开始写作{picked.length?' · '+picked.length:''}</button></>}
    {mode==='edit'&&draft&&<><div style={{display:'grid',gap:8,margin:'10px 0'}}>{draft.materials?.map((r,i)=>{
      const key=r.type+'|'+r.id, excerpt=draft.coverage?.[key];
      return <details key={key} open={draft.materials.length===1&&i===0}><summary>{r.title}</summary>
        <div style={{whiteSpace:'pre-wrap',overflow:'auto',maxHeight:180,padding:9}} onMouseUp={e=>{
          const s=window.getSelection(),text=s?.toString().trim();
          setSelection(text&&e.currentTarget.contains(s.anchorNode)&&e.currentTarget.contains(s.focusNode)?{key,text}:null);
        }}>{r.body||'暂无已核实的全文'}</div>
        {selection?.key===key&&<button onClick={()=>{edit('coverage',{...draft.coverage,[key]:selection.text});setSelection(null)}}>只写选中段落</button>}
        {excerpt&&<p>本稿选段 · {excerpt.slice(0,100)} <button onClick={()=>{const next={...draft.coverage};delete next[key];edit('coverage',next)}}>使用全文</button></p>}
      </details>})}</div>
      <input aria-label="稿件标题" style={{width:'100%',padding:8}} value={draft.title} onChange={e=>edit('title',e.target.value)}/>
      <textarea aria-label="写作正文" style={{width:'100%',minHeight:230,marginBlock:8,padding:12,resize:'vertical'}} placeholder="从这里开始写……" value={draft.body} onChange={e=>edit('body',e.target.value)}/>
      <button className="primary" disabled={busy||!draft.body.trim()} onClick={()=>action(()=>save('draft'))}>保存草稿</button>{' '}
      <button className="secondary" disabled={busy||!draft.body.trim()} onClick={()=>action(()=>save('final'))}>标记定稿</button>{' '}
      <button className="secondary" onClick={()=>setMode('pick')}>返回选材</button></>}
    {message&&<p role="status">{message}</p>}
  </section>
}

