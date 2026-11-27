import React,{useEffect,useRef} from 'react';

export const libraryTab = hash => ['map','works','quotes'].find(tab => hash === '#'+tab);

export default function PersonalLibrary({onOpenOriginal,onWriteFromLibrary}){
 const frame=useRef(null);
 const initialTab=useRef(libraryTab(location.hash)||'map');
 const detach=useRef(null);
 const write=useRef(onWriteFromLibrary);
 const writeRequest=useRef(0);
 write.current=onWriteFromLibrary;

 useEffect(()=>{
  function navigate(){
   const tab=libraryTab(location.hash);
   const child=frame.current?.contentWindow;
   if(child&&tab&&child.location.pathname==='/personal-library.html'&&child.location.hash!=='#'+tab)child.location.hash=tab;
  }
  function openSource(event){
   const element=frame.current;
   if(!element||event.origin!==location.origin||event.source!==element.contentWindow)return;
   if(event.data?.type==='yl-write-from-library'){
    const {kind,id}=event.data;
    if(!['work','quote'].includes(kind)||typeof id!=='string'||!id.trim()||!write.current)return;
    const request=++writeRequest.current;
    write.current(kind,id,()=>request===writeRequest.current&&frame.current===element&&element.isConnected&&element.contentWindow===event.source);
    return;
   }
   if(event.data?.type!=='yl-open-original')return;
   let uri;
   try{uri=new URL(event.data.uri);}catch{return;}
   if(uri.protocol==='obsidian:'&&uri.hostname==='open')onOpenOriginal(uri.href);
  }
  window.addEventListener('hashchange',navigate);
  window.addEventListener('message',openSource);
  return ()=>{
   window.removeEventListener('hashchange',navigate);
   window.removeEventListener('message',openSource);
   detach.current?.();
  };
 },[onOpenOriginal]);

 function listenToTabs(){
  detach.current?.();
  const child=frame.current.contentWindow;
  const sync=()=>{
   const tab=libraryTab(child.location.hash);
   if(tab&&location.hash!=='#'+tab)history.replaceState(history.state,'','#'+tab);
  };
  const requested=libraryTab(location.hash);
  if(requested&&requested!==libraryTab(child.location.hash))child.location.hash=requested;
  child.addEventListener('hashchange',sync);
  detach.current=()=>child.removeEventListener('hashchange',sync);
 }

 return <iframe ref={frame} className="personal-library-frame" title="我的知识库" src={'/personal-library.html?embedded=1#'+initialTab.current} onLoad={listenToTabs}/>;
}
