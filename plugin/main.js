const {Plugin,ItemView,Notice,PluginSettingTab,Setting}=require('obsidian');
const {spawn}=require('child_process');
const path=require('path'),fs=require('fs'),os=require('os'),http=require('http'),crypto=require('crypto');
const VIEW='yl-knowledge-workbench-view';
function health(address){return new Promise(resolve=>{const req=http.get(address+'/api/health',res=>{let body='';res.on('data',x=>body+=x);res.on('end',()=>{try{const h=JSON.parse(body);resolve(h.app==='yl-knowledge-workbench'?h:null)}catch{resolve(null)}})});req.setTimeout(1500,()=>{req.destroy();resolve(null)});req.on('error',()=>resolve(null))})}
function readJson(p){return JSON.parse(fs.readFileSync(p,'utf8').replace(/^\uFEFF/,''))}
function refresh(address){return new Promise((resolve,reject)=>{const req=http.request(address+'/api/reload',{method:'POST',headers:{'X-Knowledge-Client':'workbench','Content-Type':'application/json','Content-Length':2}},res=>{res.resume();res.on('end',()=>res.statusCode===200?resolve():reject(Error('刷新知识库未成功。')))});req.setTimeout(60000,()=>req.destroy(Error('刷新知识库超时。')));req.on('error',reject);req.end('{}')})}
function pathKey(p){return process.platform==='win32'?path.resolve(p).toLowerCase():path.resolve(p)}
function samePath(a,b){return !!a&&!!b&&pathKey(a)===pathKey(b)}

class WorkbenchView extends ItemView{
 constructor(leaf,plugin){super(leaf);this.plugin=plugin}
 getViewType(){return VIEW} getDisplayText(){return '知识工作台'} getIcon(){return 'network'}
 async onOpen(){
  this._closed=false;clearInterval(this.monitor);if(this.listener)window.removeEventListener('message',this.listener);
  this.contentEl.empty();this.contentEl.style.padding='0';this.contentEl.style.overflow='hidden';
  const loading=this.contentEl.createDiv({text:'正在连接你的知识库…',cls:'yl-workbench-loading'});
  try{
   await this.plugin.ensureService();if(this._closed)return;
   const address=this.plugin.address;loading.remove();
   this.frame=this.contentEl.createEl('iframe',{attr:{src:address+'/',title:'知识工作台',style:'width:100%;height:100%;border:0;display:block;background:#faf7f2;'}});
   this.monitor=setInterval(()=>this.reconnect(),15000);
   this.listener=event=>{
    if(event.origin!==address||event.source!==this.frame.contentWindow||event.data?.type!=='yl-open-original')return;
    try{
     const uri=new URL(event.data.uri);if(uri.protocol!=='obsidian:'||uri.hostname!=='open'||uri.searchParams.get('vault')!==this.app.vault.getName())return;
     const file=uri.searchParams.get('file');if(!file||file.split(/[\\/]/).includes('..')||file.startsWith('/')||file.includes(':'))return;
     const abstract=this.app.vault.getAbstractFileByPath(file);if(abstract?.extension==='md')this.app.workspace.getLeaf('tab').openFile(abstract);
    }catch{new Notice('原文件无法打开。')}
   };window.addEventListener('message',this.listener);
  }catch(e){loading.textContent='工作台暂未启动：'+e.message;this.contentEl.createEl('button',{text:'重新连接'}).onclick=()=>this.onOpen()}
 }
 async reconnect(){
  if(this._closed||this.reconnecting||Date.now()<(this.retryAfter||0))return;
  this.reconnecting=true;
  try{if(!await health(this.plugin.address)){await this.plugin.ensureService();if(!this._closed)this.frame?.contentWindow?.postMessage({type:'yl-service-restored'},this.plugin.address)}this.retryAfter=0;this.notified=false}
  catch{this.retryAfter=Date.now()+60000;if(!this.notified){new Notice('工作台连接暂时中断，可在设置中检查连接。');this.notified=true}}
  finally{this.reconnecting=false}
 }
 async onClose(){this._closed=true;clearInterval(this.monitor);if(this.listener)window.removeEventListener('message',this.listener)}
}
class WorkbenchSettings extends PluginSettingTab{
 constructor(app,plugin){super(app,plugin);this.plugin=plugin}
 display(){
  const el=this.containerEl;el.empty();el.createEl('h2',{text:'知识工作台'});
  el.createEl('p',{text:'读取当前 Obsidian 库。原文、头像、对话和个人设置保存在本机；调用模型时会发送所需材料。名称与头像修改后点击下方“应用并打开”。Python 路径在服务下次启动时生效。'});
  const fields=[['python','Python 路径','Python 3.12 或以上，需安装 PyYAML；Windows 自动使用无窗口运行方式。'],['name','助手名称','使用自己的名称；留空显示“我的知识助手”。'],['model','Codex 模型 ID','填写你账号可用的模型 ID；留空使用 gpt-6-astra，修改后点击应用。'],['avatar','头像路径','可选，选择本机图片的完整路径。'],['profilePath','已有知识库配置','已有 YL 知识库可指定 profile.json；一般用户留空即可。']];
  for(const [key,label,desc] of fields)new Setting(el).setName(label).setDesc(desc).addText(t=>t.setValue(this.plugin.settings[key]??this.plugin.config?.profile?.workbench?.[key]??'').onChange(async v=>{this.plugin.settings[key]=v.trim();await this.plugin.saveData(this.plugin.settings)}));
  new Setting(el).setName('打开工作台').setDesc('无需开启终端，插件会在后台连接。').addButton(b=>b.setButtonText('应用并打开').onClick(()=>this.plugin.open()));
 }
}
module.exports=class KnowledgeWorkbench extends Plugin{
 async onload(){
  this.settings=(await this.loadData())||{};this.addSettingTab(new WorkbenchSettings(this.app,this));
  try{this.configure()}catch(e){new Notice(e.message)}
  this.registerView(VIEW,leaf=>new WorkbenchView(leaf,this));
  this.addRibbonIcon('network','打开知识工作台',()=>this.open());this.addCommand({id:'open',name:'打开知识工作台',callback:()=>this.open()});
  this.registerObsidianProtocolHandler('yl-knowledge-workbench',()=>this.open());
 }
 configure(){
  const root=this.app.vault.adapter.getBasePath(),globalPath=path.join(os.homedir(),'.config','yl-toolbox','profile.json');
  let globalProfile={};try{globalProfile=readJson(globalPath)}catch{}
  let profilePath=this.settings.profilePath||(samePath(root,globalProfile.knowledge_root)?globalPath:null);
  let profile;
  if(profilePath){
   profile=readJson(profilePath);if(!samePath(root,profile.knowledge_root))throw Error('所选配置不属于当前库。');
   let changed=false;profile.workbench=profile.workbench||{};
   for(const key of ['name','avatar','model'])if(Object.hasOwn(this.settings,key)){const value=this.settings[key]||(key==='name'?'我的知识助手':'');if(profile.workbench[key]!==value){profile.workbench[key]=value;changed=true}}
   if(changed){fs.writeFileSync(profilePath,JSON.stringify(profile,null,2),'utf8');this.needsRefresh=true}
  }
  else{
   const id=crypto.createHash('sha256').update(pathKey(root)).digest('hex').slice(0,12);
   const runtime=path.join(os.homedir(),'.config','yl-workbench',id);fs.mkdirSync(runtime,{recursive:true});
   profilePath=path.join(runtime,'profile.json');
   profile=fs.existsSync(profilePath)?readJson(profilePath):{};
   if(profile.knowledge_root&&!samePath(root,profile.knowledge_root))throw Error('本机配置属于另一个库，已停止覆盖。');
   profile.adapter='markdown';profile.knowledge_root=root;
   profile.workbench={name:'我的知识助手',avatar:'',model:'gpt-6-astra',runtime,port:8800+parseInt(id.slice(0,4),16)%1000,...profile.workbench};
   for(const key of ['name','avatar','model'])if(Object.hasOwn(this.settings,key))profile.workbench[key]=this.settings[key]||(key==='name'?'我的知识助手':key==='model'?'gpt-6-astra':'');
   profile.retrieval={python:globalProfile.retrieval?.python||'',...profile.retrieval};
   if(this.settings.python)profile.retrieval.python=this.settings.python;
   const encoded=JSON.stringify(profile,null,2);if(!fs.existsSync(profilePath)||fs.readFileSync(profilePath,'utf8')!==encoded){fs.writeFileSync(profilePath,encoded,'utf8');this.needsRefresh=true}
  }
  const port=Number(profile.workbench?.port||8766);if(!Number.isInteger(port)||port<1024||port>65535)throw Error('本机端口无效。');
  this.address='http://127.0.0.1:'+port;this.config={root,profilePath,profile,port};
 }
 async open(){try{this.configure();await this.ensureService();const leaves=this.app.workspace.getLeavesOfType(VIEW),leaf=leaves[0]||this.app.workspace.getLeaf('tab');if(!leaves.length)await leaf.setViewState({type:VIEW,active:true});else if(!leaf.view.frame)await leaf.view.onOpen();else leaf.view.frame.contentWindow?.postMessage({type:'yl-service-restored'},this.address);await this.app.workspace.revealLeaf(leaf)}catch(e){new Notice(e.message)}}
 async ensureService(){
  if(!this.config)this.configure();
  const h=await health(this.address);if(h){if(h.vault&&!samePath(h.vault,this.config.root))throw Error('该端口正在服务另一个知识库。');if(this.needsRefresh){await refresh(this.address);this.needsRefresh=false}return}
  if(!this.starting)this.starting=(async()=>{
   const {root,profilePath,profile,port}=this.config;
   const bundled=path.join(root,this.manifest.dir,'backend','server.py');
   const server=fs.existsSync(bundled)?bundled:path.join(root,'90_系统资料','系统导航','09_知识工作台','server.py');
   const configured=this.settings.python||profile.retrieval?.python;
   const python=process.platform==='win32'&&configured?path.join(path.dirname(configured),'pythonw.exe'):configured;
   if(!python||!fs.existsSync(server)||!fs.existsSync(python))throw Error('请在插件设置中指定 Python 环境。');
   const runtime=profile.workbench?.runtime||path.join(os.homedir(),'.config','yl-toolbox','runtime','knowledge-workbench');fs.mkdirSync(runtime,{recursive:true});
   const log=fs.openSync(path.join(runtime,'plugin-server.log'),'a');let launchError;
   const child=spawn(python,['-B','-X','utf8',server,'--profile',profilePath,'--port',String(port)],{cwd:path.dirname(server),detached:true,windowsHide:true,stdio:['ignore',log,log]});child.unref();fs.closeSync(log);child.on('error',e=>{launchError=e});
   for(let i=0;i<90;i++){const ready=await health(this.address);if(ready){if(ready.vault&&!samePath(ready.vault,root))throw Error('本机端口已被另一个知识库使用。');this.needsRefresh=false;return}if(launchError)throw launchError;await new Promise(r=>setTimeout(r,700))}
   throw Error('本地服务尚未就绪，请检查 Python 与 PyYAML 是否安装。');
  })().finally(()=>{this.starting=null});return this.starting;
 }
 onunload(){/* Keep the background service available to browser readers. */}
};
