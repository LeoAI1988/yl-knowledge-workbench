'use strict';
(async function followActiveWorkbench(){
  if (!['127.0.0.1','localhost'].includes(location.hostname)) return;
  // Old bookmarks to a section should reopen that section inside the workbench.
  if(location.pathname==='/personal-library.html'&&new URLSearchParams(location.search).get('embedded')!=='1'){
    const home=new URL('/',location.href);
    home.hash=['#works','#quotes','#map'].includes(location.hash)?location.hash:'#map';
    location.replace(home.href);
    return;
  }
  try {
    const [health,route]=await Promise.all(['/api/health','/active-service.json'].map(async name=>{
      const response=await fetch(name,{cache:'no-store',redirect:'error'});
      if(!response.ok) throw new Error('unavailable');
      return response.json();
    }));
    if(health.app!=='yl-knowledge-workbench' || health.vault!==route.vault ||
       !Number.isInteger(route.port) || route.port<1024 || route.port>65535 || route.port===Number(location.port)) return;
    const next=new URL(location.href);
    next.port=String(route.port);
    next.searchParams.set('qa-upgrade','1');
    location.replace(next.href);
  } catch {}
})();
