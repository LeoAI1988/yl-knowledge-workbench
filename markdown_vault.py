"""Portable adapter for an ordinary vault; never infer atoms from every file."""
import os,re,time,threading
from pathlib import Path
from collections import Counter
from types import SimpleNamespace
from knowledge import Knowledge,parse_md,read_json,sha,text_clean,reading_text,as_list,TYPES

class MarkdownVault(Knowledge):
    def __init__(self,profile):
        self.profile_path=Path(profile);self.profile=read_json(profile);self.root=Path(self.profile['knowledge_root']).resolve()
        self.retrieval_lock=threading.Lock();self.rargs=()
        self.retrieval=SimpleNamespace(status=lambda:{'documents':len(self.sources),'stale_sources':[],'semantic_pending':0,'mode':'本地文字检索'})
        self.reload()

    def files(self):
        excluded=set(self.profile.get('workbench',{}).get('exclude_folders',[]))|{'80_私人档案','90_系统资料','node_modules'}
        for parent,dirs,files in os.walk(self.root,followlinks=False):
            dirs[:]=[d for d in dirs if not d.startswith('.') and d not in excluded and not Path(parent,d).is_symlink() and not Path(parent,d).is_junction()]
            for name in files:
                p=Path(parent,name)
                if p.suffix.lower()=='.md' and not p.is_symlink() and p.resolve().is_relative_to(self.root):yield p

    def _signature(self):return [(str(p),p.stat().st_mtime_ns,p.stat().st_size) for p in self.files()]

    def reload(self):
        self.sources={};self.source_by_path={};self.source_hashes={};self.nodes={};self.expressions={};self.works=[];self.topics=[];self.discourses=[];self.relations=[];self._docs={};self._meta={};paths={}
        for p in self.files():
            try:m,b=parse_md(p)
            except (OSError,ValueError,__import__('yaml').YAMLError):continue
            if not isinstance(m,dict):continue
            if m.get('privacy') in ('P2','P3','private') or m.get('index') is False:continue
            sid='file-'+sha(p.relative_to(self.root).as_posix())[:20]
            title=m.get('title') or (re.search(r'^#\s+(.+)$',b,re.M)[1] if re.search(r'^#\s+(.+)$',b,re.M) else p.stem)
            kind=str(m.get('type','source'));ds=[str(d) for d in as_list(m.get('domains') or m.get('领域'))] or ['pending']
            row={'source_id':sid,'title':str(title),'path':str(p),'kind':'work' if kind in ('work','作品') else 'source','authorship':m.get('authorship','unknown'),'review_status':m.get('review_status','unreviewed'),'related_ids':[]}
            self.sources[sid]=row;self.source_by_path[str(p.resolve()).casefold()]=row;self.source_hashes[str(p.resolve()).casefold()]=sha(p.read_bytes())
            self._docs[sid]=b;self._meta[sid]=m;paths[p.relative_to(self.root).with_suffix('').as_posix()]=sid
            atom_type=kind.upper()
            if atom_type in TYPES or kind in ('atom','知识原子'):
                atom_type=atom_type if atom_type in TYPES else 'OPI';oid=str(m.get('id') or sid)
                if oid in self.nodes:oid=sid
                row['related_ids']=[oid]
                self.nodes[oid]={'id':oid,'title':str(title),'type':atom_type,'kind':TYPES[atom_type],'domains':ds,'themes':as_list(m.get('tags')),'quote':text_clean(m.get('verbatim_core') or b),'quote_label':'笔记内容','authorship':row['authorship'],'degree':0,'state':'可查阅','writing_status':'research_only','updated_at':str(m.get('updated_at','')),'explanation':''}
            if kind in ('expression','表达资产'):
                self.expressions[sid]={'id':sid,'text':text_clean(b),'label':'表达笔记','roles':as_list(m.get('roles')) or ['原话'],'node_ids':[],'domains':ds,'source_id':sid}
            if row['kind']=='work':
                self.works.append({'id':sid,'work_id':str(m.get('work_id','')),'title':str(title),'platform':m.get('platform','作品'),'status':m.get('status','已保存'),'date':str(m.get('date','')),'node_ids':[],'source':self.source_ref(p),'path':p,'uri':self.uri(p)})
        # Resolve only actual wikilinks. Ambiguous basename links remain unresolved.
        basenames={}
        for rel,sid in paths.items():basenames.setdefault(Path(rel).name,[]).append(sid)
        for sid,b in self._docs.items():
            for raw in re.findall(r'\[\[([^\]|#]+)',b):
                target=paths.get(raw)
                if not target and len(basenames.get(raw,[]))==1:target=basenames[raw][0]
                if not target:continue
                a=self.sources[sid]['related_ids'];z=self.sources[target]['related_ids']
                for x in a:
                    for y in z:
                        if x!=y:self.relations.append({'id':'link-'+sha(x+y)[:18],'source':x,'target':y,'type':'关联','evidence':'笔记中的双向链接'})
                if sid in self.expressions:self.expressions[sid]['node_ids']+=z
                for work in self.works:
                    if work['id']==sid:work['node_ids']=list(dict.fromkeys(work['node_ids']+z))
        # Generic wikilinks express association, including reciprocal links.
        self.relations=list({tuple(sorted((r['source'],r['target']))):r for r in reversed(self.relations)}.values())
        degrees=Counter(x for r in self.relations for x in (r['source'],r['target']))
        for n in self.nodes.values():n['degree']=degrees[n['id']]
        self.signature=self._signature();self.loaded_at=time.time()

    def bootstrap(self):
        self.ensure_fresh();counts=Counter(d for n in self.nodes.values() for d in n['domains'])
        domains=list(dict.fromkeys([*counts,*[d for e in self.expressions.values() for d in e['domains']]]))
        return {'identity':{'name':self.profile.get('workbench',{}).get('name','我的知识助手')},'nodes':list(self.nodes.values()),'edges':self.relations,'domains':[{'id':d,'title':'待归类' if d=='pending' else d,'description':'','color':'#c4866b','count':counts[d]} for d in domains], 'expressions':list(self.expressions.values()),'discourses':[],'topics':[],
            'stats':{'atoms':len(self.nodes),'expressions':len(self.expressions),'topics':0,'works':len(self.works),'characters':sum(len(re.sub(r'\s','',b)) for b in self._docs.values()),'documents':len(self.sources),'relations':len(self.relations)},'metrics_note':'读取当前库中允许索引的 Markdown 正文；知识原子与表达资产来自明确的类型标记，普通笔记保留在原始资料库。','data_date':'','sample_id':next(iter(self.nodes),None)}

    def detail(self,oid):
        self.ensure_fresh()
        if oid not in self.nodes:raise KeyError('未找到该知识。')
        source=next(r for r in self.sources.values() if oid in r['related_ids'])
        return {**self.nodes[oid],'context':'','progression':[],'usage':'','boundary':'','sources':[self.source_ref(source['path'])],'relations':[{**r,'other':self.nodes[r['target'] if r['source']==oid else r['source']]} for r in self.relations if oid in (r['source'],r['target'])],'works':[{k:v for k,v in w.items() if k!='path'} for w in self.works if oid in w['node_ids']],'expressions':[e for e in self.expressions.values() if oid in e['node_ids']],'discourses':[],'uri':self.uri(source['path'])}

    def source(self,sid):
        self.ensure_fresh()
        row=self.sources.get(sid)
        if not row:raise KeyError('来源未在当前资料库中。')
        ref=self.source_ref(row['path'])
        if ref['changed']:self.reload();return self.source(sid)
        return {**ref,'sections':[{'text':reading_text(self._docs[sid])}],'authorship':row['authorship'],'review_status':row['review_status']}

    def search(self,query):
        self.ensure_fresh();terms=re.findall(r'[a-zA-Z0-9]+|[\u4e00-\u9fff]{2,}',query.lower())
        terms=list(dict.fromkeys(terms+[t[i:i+2] for t in terms if len(t)>3 for i in range(len(t)-1)]))
        ranked=sorted(((sum((r['title']+' '+self._docs[sid]).lower().count(t) for t in terms),sid) for sid,r in self.sources.items()),reverse=True)
        passages=[]
        for score,sid in ranked:
            if not score or len(passages)>=8:break
            r=self.sources[sid];passages.append({'citation':'S'+str(len(passages)+1),'source_id':sid,'title':r['title'],'text':self._docs[sid][:10000],'context':[],'lines':[],'authorship':r['authorship'],'review_status':r['review_status'],'quote_ready':False,'source_hash':self.source_hashes[str(Path(r['path']).resolve()).casefold()],'node_ids':r['related_ids'],'uri':self.uri(r['path'])})
        return {'passages':passages,'semantic':False,'warnings':['当前使用本地文字检索；引用须核对来源。'],'seconds':0}
