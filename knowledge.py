"""Read projections over the existing canonical vault. No source rewriting."""
from __future__ import annotations
import csv, hashlib, importlib.util, json, re, sqlite3, threading, time
from collections import Counter
from contextlib import closing
from pathlib import Path
from urllib.parse import quote
import yaml

DOMAINS = [('D03','AI与个人能力','把经验变成可调用的能力','#56d6c9'),('D02','商业与公司经营','组织、产品与长期积累','#a69af5'),('D01','建筑与空间','从造房子到组织生活','#edb771'),('D06','传播与获客','流量、IP与表达','#ea8fb9'),('D04','历史与文明','比较、变迁与人的处境','#8bb9e9'),('D05','认知与学习','知识如何进入你的体系','#a6c879'),('D07','文学与生活','审美、记忆与日常','#c9a180')]
TYPES={'OPI':'观点','SOL':'方法','QST':'问题','REF':'参考','CON':'概念','CHAIN':'论述链','QUO':'金句','EXP':'经历与表达','CAS':'案例','MET':'方法'}
ROLES={'metaphor':'比喻','contrast':'对照','judgment':'判断','rhythm':'节奏','gold_line':'金句','progression':'递进','opening':'开头','closing':'收束'}

def sha(value): return hashlib.sha256(value if isinstance(value,bytes) else value.encode('utf-8')).hexdigest()
def read_json(path): return json.loads(Path(path).read_text('utf-8-sig'))
def parse_md(path):
    text=Path(path).read_text('utf-8-sig')
    m=re.match(r'^---\r?\n(.*?)\r?\n---(?:\r?\n|$)',text,re.S)
    return (yaml.safe_load(m.group(1)) or {},text[m.end():].strip()) if m else ({},text.strip())
def text_clean(value):
    text=str(value or '')
    text=re.sub(r'!?(\[\[)([^\]|]+)(?:\|([^\]]+))?\]\]',lambda m:m.group(3) or m.group(2).split('/')[-1],text)
    return re.sub(r'<!--.*?-->','',text,flags=re.S).strip()
def section(body, names):
    for name in names:
        m=re.search(r'^##\s+'+re.escape(name)+r'\s*\n(.*?)(?=^##\s|\Z)',body,re.M|re.S)
        if m: return text_clean(m.group(1))
    return ''
def as_list(value): return value if isinstance(value,list) else ([value] if value else [])

def reading_text(value):
    """Presentation only. Never change source bytes or source line positions."""
    lines=[]
    for line in text_clean(value).splitlines():
        plain=re.sub(r'^\s*(?:>\s*)?(?:[-*]\s*)?','',line).strip().lstrip('*').strip()
        if re.match(r'^(?:转写|转写引擎|转写参数|源SHA-256|SHA-256|源文件|原始文件路径|录音路径|音频路径)\s*[:：]',plain):continue
        if re.match(r'^(?:说明|备注|注意|提示)\s*[:：]',plain) and re.search(r'ASR|人工校[订对]|识别噪声|转写参数|faster.whisper',plain,re.I):continue
        if re.match(r'^(?:本稿|本文件|本逐字稿|本转写)',plain) and re.search(r'ASR|未经.*校|未.*核听|转写噪声|机器转写',plain,re.I):continue
        if re.match(r'^[⚠️\s]*(?:ASR\s*文本|机器转写说明)',plain,re.I):continue
        if re.match(r'^\|\s*(?:objectId|source_id|SHA-256|源文件路径|分辨率)\s*\|',plain,re.I):continue
        if plain.startswith('来源：') or plain.startswith('来源:'):
            line=re.sub(r'[（(][^（）()\n]*(?:指示|本地无可靠文稿)[^（）()\n]*[）)]','',line).strip()
        lines.append(line)
    return '\n'.join(lines).strip()

def metric_number(value):
    try:return float(str(value).replace(',','')) if value not in (None,'') else None
    except (ValueError,TypeError):return None

def topic_summary(metrics,conversions):
    # One representative publication, latest snapshot supplied by read_topics.
    # Do not sum cumulative snapshots or combine one work's views with another's rate.
    measured=[m for m in metrics if metric_number(m.get('views')) is not None]
    representative=max(measured,key=lambda m:metric_number(m['views'])) if measured else (metrics[0] if metrics else {})
    rows=[c for c in conversions if c.get('publication_id')==representative.get('publication_id')]
    numbers=[metric_number(c.get('content_attributed_orders')) for c in rows]
    sale='有' if any(n is not None and n>0 for n in numbers) else ('无' if numbers and all(n==0 for n in numbers) else '待补')
    return {**{k:representative.get(k) for k in ('publication_id','title','views','follows','completion_rate','captured_at')},'sale':sale,'publication_count':len(metrics),'basis':'多条作品时展示播放最高的一条；成交仅指已记录的该作品归因窗口。'}

class Knowledge:
    def __init__(self, profile_path):
        self.profile_path=Path(profile_path); self.profile=read_json(profile_path)
        self.root=Path(self.profile['knowledge_root']).resolve()
        self.network=self.root/'90_系统资料/系统导航/06_统一知识网络'
        self.reader=self.root/'90_系统资料/系统导航/07_阅读入口'
        self.retrieval_lock=threading.Lock()
        script=Path(self.profile['core_root'])/'yl-knowledge-search/scripts/retrieval.py'
        if not script.exists(): script=Path.home()/'.codex/skills/yl-knowledge-search/scripts/retrieval.py'
        spec=importlib.util.spec_from_file_location('yl_retrieval',script)
        self.retrieval=importlib.util.module_from_spec(spec); spec.loader.exec_module(self.retrieval)
        self.rargs=self.retrieval.config(profile_path)
        self.reload()

    def reload(self):
        rows=read_json(self.network/'统一对象索引.json')
        self.rows={r['id']:r for r in rows if r.get('canonical') and r.get('graph_visible') and r.get('privacy') in ('P0','P1')}
        self.relations=[dict(r,id='rel-'+str(i)) for i,r in enumerate(read_json(self.network/'统一关系索引.json')) if r['source'] in self.rows and r['target'] in self.rows]
        self.degrees=Counter([x for r in self.relations for x in (r['source'],r['target'])])
        self.nodes={}; self.expressions={}; self._details={}
        self.manifest=read_json(self.profile['retrieval']['manifest'])['sources']
        self.sources={r['source_id']:r for r in self.manifest if r.get('index',True) and self.retrieval.source_allowed(r,self.profile,self.root)[0]}
        self.source_by_path={str(Path(r['path']).resolve()).casefold():r for r in self.sources.values()}
        with closing(sqlite3.connect(Path(self.profile['retrieval']['index_dir'])/'text.sqlite3')) as db:
            self.source_hashes={str(Path(p).resolve()).casefold():h for p,h in db.execute('select path,hash from docs')}
        for oid,r in self.rows.items():
            path=self.root/r['path']
            if not path.is_file(): continue
            meta,body=parse_md(path)
            quote_text=meta.get('verbatim_core','')
            if isinstance(quote_text,list): quote_text='\n'.join(map(str,quote_text))
            if not quote_text:
                quote_text='\n'.join(re.findall(r'^>\s?(.*)$',body,re.M))[:1200]
            unavailable=r.get('writing_status') in ('source_unavailable','historical_reference') or r.get('confirmation_state')=='source_unavailable'
            adopted=r.get('writing_status')=='user_adopted'
            own=r.get('authorship') in ('user_owned','user_owned_chat_expression')
            quote_label='内化观点 · 转述' if adopted else ('本人材料原句' if own else '原稿摘录 · 归属须结合来源')
            self.nodes[oid]={'id':oid,'title':r['title'],'type':r['type'],'kind':TYPES.get(r['type'],'知识'),
                'domains':r.get('domains') or ['pending'],'themes':r.get('themes',[]),'quote':text_clean(r.get('safe_view') if adopted else quote_text),'quote_label':quote_label,'authorship':r.get('authorship'),
                'degree':self.degrees[oid],'state':'原件待补' if unavailable else ('内化观点' if r.get('writing_status')=='user_adopted' else '可查阅'),
                'writing_status':r.get('writing_status'),'updated_at':str(meta.get('updated_at','')),
                'core_source':Path(str(meta.get('verbatim_source',''))).stem,
                'explanation':section(body,['原子内容','核心观点','核心内容'])[:1800]}
            self._details[oid]=(meta,body)
            variants=[{'verbatim':quote_text,'source':meta.get('verbatim_source'),'locator':meta.get('verbatim_locator'),'roles':meta.get('expression_roles',[])}]
            variants+=as_list(meta.get('verbatim_variants'))
            for v in variants:
                if not isinstance(v,dict): continue
                q=str(v.get('verbatim','')).strip()
                if not q or unavailable or adopted or r.get('writing_status') not in ('activated','contextual_source'): continue
                key=sha(re.sub(r'\s+','',q))[:18]
                roles=as_list(v.get('roles') or meta.get('expression_roles'))
                item=self.expressions.setdefault(key,{'id':key,'text':text_clean(q),'label':'本人材料原句' if own else '表达候选 · 查看来源归属','roles':[],'node_ids':[],'domains':[]})
                item['roles']=list(dict.fromkeys(item['roles']+[ROLES.get(x,x) for x in roles])) or ['原话']
                item['node_ids']=list(dict.fromkeys(item['node_ids']+[oid])); item['domains']=list(dict.fromkeys(item['domains']+(r.get('domains') or ['pending'])))
        self.discourses=read_json(self.network/'完整论述索引.json')
        self.works=self.read_works()
        self.topics=self.read_topics()
        self.signature=self._signature()
        self.loaded_at=time.time()

    def _signature(self):
        files=[self.network/'统一对象索引.json',self.network/'统一关系索引.json',Path(self.profile['retrieval']['manifest'])]
        files+=list((self.root/'05_知识原子/条目').glob('*.md'))
        files+=list((self.reader/'作品索引').glob('*.md'))
        files+=list((self.root/'02_我的作品全集/工作台草稿').glob('*.md'))
        files+=list((self.root/'03_选题库/选题').glob('*.md'))
        files+=list((self.root/'90_系统资料/内容生产/AI业务/04_发布与数据/00_统一台账').glob('*.csv'))
        return [(str(p),p.stat().st_mtime_ns,p.stat().st_size) for p in files if p.exists()]

    def ensure_fresh(self):
        if time.time()-self.loaded_at>15:
            if self._signature()!=self.signature: self.reload()
            else: self.loaded_at=time.time()

    def uri(self, path):
        p=Path(path)
        if not p.is_absolute(): p=self.root/p
        try: rel=p.resolve().relative_to(self.root).as_posix()
        except ValueError: return None
        return 'obsidian://open?vault='+quote(self.root.name)+'&file='+quote(rel)

    def source_ref(self, path):
        row=self.source_by_path.get(str(Path(path).resolve()).casefold())
        if not row: return None
        p=Path(row['path']); key=str(p.resolve()).casefold()
        changed=self.source_hashes.get(key)!=sha(p.read_bytes())
        return {'id':row['source_id'],'title':row.get('title') or p.stem,'state':'原文已变化，待更新' if changed else '可回源','changed':changed,'uri':self.uri(p)}

    def detail(self, oid):
        if oid not in self.nodes: raise KeyError('未找到该知识。')
        meta,body=self._details[oid]; row=self.rows[oid]
        sources=[self.source_ref(p) for p in as_list(meta.get('source_documents'))]
        if meta.get('verbatim_source'): sources.insert(0,self.source_ref(meta['verbatim_source']))
        sources=list({s['id']:s for s in sources if s}.values())
        relations=[{**r,'other':self.nodes[r['target'] if r['source']==oid else r['source']]} for r in self.relations if oid in (r['source'],r['target'])]
        works=[w for w in self.works if oid in w['node_ids']]
        progress=meta.get('progression') or []
        if isinstance(progress,str): progress=[{'role':'完整推进','verbatim':progress}]
        return {**self.nodes[oid],'context':str(meta.get('verbatim_context','')),
            'progression':progress,'usage':section(body,['使用语境','适用情境','使用场景']),
            'boundary':section(body,['不适用边界','边界','适用边界']),
            'safe_view':row.get('safe_view'),'sources':sources,'relations':relations,'works':works,
            'expressions':[e for e in self.expressions.values() if oid in e['node_ids']],
            'discourses':[{'id':d['id'],'title':d['title']} for d in self.discourses if oid in d.get('object_ids',[])],
            'uri':self.uri(row['path']),'authorship':row.get('authorship'),'confirmation':row.get('confirmation_state')}

    def read_works(self):
        out=[]
        node_paths={}
        for oid,r in self.rows.items():
            for raw in r.get('source_documents',[]):
                node_paths.setdefault(str(Path(raw).absolute()).casefold().replace('\\','/'),[]).append(oid)
        for path in (self.reader/'作品索引').glob('*.md'):
            m,_=parse_md(path); raw=m.get('canonical_body')
            if not raw: continue
            p=(self.root/raw).resolve()
            if not p.is_relative_to(self.root) or not p.exists(): continue
            nodes=node_paths.get(str(p).casefold().replace('\\','/'),[])
            out.append({'id':m.get('asset_id',path.stem),'work_id':m.get('work_id',''),'title':m.get('标题',path.stem),
                'platform':m.get('平台',''),'status':m.get('阅读状态','待核实'),'date':str(m.get('发布时间','')),
                'node_ids':nodes,'source':self.source_ref(p),'path':p,'uri':self.uri(p)})
        known={str(w['path']).casefold() for w in out}
        for row in self.sources.values():
            p=Path(row['path']).resolve()
            if row.get('kind')!='work' or str(p).casefold() in known:continue
            meta,_=parse_md(p)
            out.append({'id':row['source_id'],'work_id':meta.get('work_id',''),'title':row.get('title') or p.stem,
                'platform':meta.get('platform') or ('视频号' if '视频号' in str(p) else '公众号' if '公众号' in str(p) else '其他作品'),
                'status':'已保存','date':str(meta.get('published_at') or meta.get('date','')),
                'node_ids':[x for x in row.get('related_ids',[]) if x in self.nodes],'source':self.source_ref(p),'path':p,'uri':self.uri(p)})
            known.add(str(p).casefold())
        for p in (self.root/'02_我的作品全集/工作台草稿').glob('*.md'):
            if p.is_symlink() or not p.resolve().is_relative_to(self.root) or str(p.resolve()).casefold() in known:continue
            meta,body=parse_md(p)
            if meta.get('status')!='draft_not_final' or meta.get('privacy') in ('P2','P3','private'):continue
            title=re.search(r'^#\s+(.+)',body,re.M)
            out.append({'id':meta.get('id',p.stem),'work_id':'','title':title[1] if title else p.stem,'platform':'工作台初稿','status':'尚未定稿',
                'date':str(meta.get('created_at','')),'node_ids':[],'source':None,'path':p,'uri':self.uri(p)})
        return out

    def read_topics(self):
        base=self.root/'90_系统资料/内容生产/AI业务/04_发布与数据/00_统一台账'
        def csvread(n):
            with (base/n).open(encoding='utf-8-sig',newline='') as f: return list(csv.DictReader(f))
        pubs=csvread('发布记录.csv'); metrics=csvread('内容表现.csv'); conversions=csvread('业务转化.csv')
        result=[]
        for path in (self.root/'03_选题库/选题').glob('*.md'):
            m,b=parse_md(path); work_ids=set(as_list(m.get('source_work_ids')))
            linked_pubs=[p for p in pubs if p['work_id'] in work_ids and p['platform'] in ('wechat_channels','wechat_official')]
            pub_ids={p['publication_id'] for p in linked_pubs}
            snapshots=[r for r in metrics if r['publication_id'] in pub_ids]
            latest={}
            for s in sorted(snapshots,key=lambda x:x.get('captured_at','')): latest[s['publication_id']]=s
            works=[w for w in self.works if w['work_id'] in work_ids or w['id'] in as_list(m.get('source_asset_ids'))]
            conv=[{k:r[k] for k in ('publication_id','product_name','window_start','window_end','content_attributed_orders','content_attributed_revenue','attribution_basis','captured_at')} for r in conversions if r['publication_id'] in pub_ids]
            result.append({'id':m.get('topic_id',path.stem),'title':m.get('title',path.stem),'date':str(m.get('last_validated_at','')),
                'mechanism':section(b,['可复用机制']),'boundary':section(b,['边界与反例']),
                'works':[{k:v for k,v in w.items() if k!='path'} for w in works],
                'node_ids':list(dict.fromkeys(n for w in works for n in w['node_ids'])),
                'metrics':[{k:r.get(k) or None for k in ('publication_id','captured_at','views','completion_rate','avg_watch_seconds','follows','title')} for r in latest.values()],
                'conversions':conv,'uri':self.uri(path),'score_state':'历史评分口径待统一'})
        for topic in result:topic['summary']=topic_summary(topic['metrics'],topic['conversions'])
        return result

    def library(self):
        self.ensure_fresh()
        works=[{k:v for k,v in w.items() if k!='path'} for w in self.works]
        sources=[]
        labels={'source':'原始记录','clean_source':'校订记录','mixed_source':'混合记录','external_reference':'参考资料'}
        for row in self.sources.values():
            if row.get('kind') not in labels:continue
            ref=self.source_ref(row['path'])
            sources.append({**ref,'category':labels[row['kind']],'node_ids':[i for i in row.get('related_ids',[]) if i in self.nodes]})
        return {'works':works,'sources':sources}

    def work(self,wid):
        entry=next((w for w in self.works if w['id']==wid),None)
        if not entry:raise KeyError('未找到这份作品。')
        if entry.get('source'):return self.source(entry['source']['id'])
        # This path comes only from the validated reader registry, never the request.
        _,body=parse_md(entry['path'])
        body=body.split('<!-- reader:works:start -->')[0].split('<!-- kp-network:start -->')[0]
        return {'id':wid,'title':entry['title'],'uri':entry['uri'],'sections':[{'text':reading_text(body)}]}

    def bootstrap(self):
        self.ensure_fresh()
        domains=[{'id':id,'title':name,'description':desc,'color':color,'count':sum(id in n['domains'] for n in self.nodes.values())} for id,name,desc,color in DOMAINS]
        pending=sum('pending' in n['domains'] for n in self.nodes.values())
        if pending:domains.append({'id':'pending','title':'待归类','description':'等更多语境，再确定所属板块','color':'#a79a8e','count':pending})
        # Count original approved text once per content hash; derived nodes are not added.
        seen=set(); total=0; documents=0
        for r in self.sources.values():
            if r.get('kind') not in ('source','clean_source','work'): continue
            p=Path(r['path']); text=p.read_text('utf-8-sig')
            content='\n'.join(b['text'] for b in self.retrieval.paragraphs(text,r))
            key=sha(content)
            if not content or key in seen: continue
            seen.add(key); documents+=1; total+=len(re.sub(r'\s','',content))
        return {'identity':{'name':self.profile.get('workbench',{}).get('name','我的知识助手')},'nodes':list(self.nodes.values()),'edges':self.relations,'domains':domains,
            'expressions':list(self.expressions.values()),'discourses':[{'id':d['id'],'title':d['title'],'domains':d['domains'],'node_ids':[i for i in d['object_ids'] if i in self.nodes]} for d in self.discourses],
            'topics':self.topics,'stats':{'atoms':len(self.nodes),'expressions':len(self.expressions),'topics':len(self.topics),'works':len(self.works),'characters':total,'documents':documents,'relations':len(self.relations)},
            'metrics_note':'文字量为已登记可检索正文的非空白字符，整篇相同内容去重；来源版本间重合段落可能仍重叠。表达量为已接入原子原话及表达变体去重数。',
            'data_date':max((t['date'] for t in self.topics),default=''), 'sample_id':max(self.nodes,key=lambda i:self.nodes[i]['degree'],default=None)}

    def source(self,sid):
        r=self.sources.get(sid)
        if not r: raise KeyError('来源未在授权检索范围中。')
        p=Path(r['path']); ref=self.source_ref(p)
        if ref['changed']: raise ValueError('这份原文已变化，引用位置需要重新核对。')
        text=p.read_text('utf-8-sig')
        sections=[{'text':reading_text(x['text']),'start':x['start'],'end':x['end'],'transcript':bool(re.match(r'^\[\d+(?:\.\d+)?-\d+(?:\.\d+)?\]',x['text'].lstrip()))} for x in self.retrieval.paragraphs(text,r)]
        return {**ref,'sections':[s for s in sections if s['text']],'authorship':r.get('authorship'),'review_status':r.get('review_status'),'reading_note':'转写文字尚待校对' if 'asr' in str(r.get('review_status','')).lower() else ''}

    def discourse(self,did):
        d=next((x for x in self.discourses if x['id']==did),None)
        if not d: raise KeyError('未找到完整论述。')
        _,body=parse_md(self.root/d['path'])
        return {'id':did,'title':d['title'],'body':text_clean(body),'uri':self.uri(d['path']),'kind':'基于原文整理的完整论述'}

    def search(self,query):
        with self.retrieval_lock:
            result=self.retrieval.search(*self.rargs,query,mode='hybrid',limit=8)
        passages=[]
        for i,r in enumerate(result['results']):
            passages.append({'citation':'S'+str(i+1),'source_id':r['source_id'],'title':r['title'],'text':r['passage'],
                'context':r['context'],'lines':r['lines'],'authorship':r.get('authorship'),'passage_authorship':r.get('passage_authorship'),'review_status':r.get('review_status'),'quote_ready':r['quote_ready'],
                'source_hash':self.source_hashes.get(str(Path(r['path']).resolve()).casefold()),
                'node_ids':[x for x in r['related_ids'] if x in self.nodes],'uri':self.uri(r['path'])})
        return {'passages':passages,'semantic':result['semantic'],'warnings':result['warnings'],'seconds':result['elapsed_seconds']}

    def evidence(self,query,node_ids=None):
        found=self.search(query)
        ids=list(dict.fromkeys((node_ids or [])+[n for p in found['passages'] for n in p['node_ids']]))[:10]
        nodes=[]
        for oid in ids:
            if oid not in self.nodes: continue
            if self.nodes[oid].get('writing_status') not in ('activated','contextual_source','user_adopted'): continue
            d=self.detail(oid)
            nodes.append({k:d.get(k) for k in ('id','title','quote','quote_label','authorship','context','progression','explanation','usage','boundary','writing_status','safe_view')})
        found['nodes']=nodes
        found['relations']=[r for r in self.relations if r['source'] in ids and r['target'] in ids]
        return found

    def verify_evidence(self,evidence):
        for passage in evidence.get('passages',[]):
            source=self.sources.get(passage['source_id'])
            if not source or not passage.get('source_hash') or sha(Path(source['path']).read_bytes())!=passage['source_hash']:
                raise ValueError('引用原文已变化或缺少版本核验，请重新分析方向再写作。')
