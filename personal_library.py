"""Shared local author library. Both clients operate on the same vault."""
import contextlib
import hashlib
import importlib.util
import json
import os
import re
import sqlite3
import sys
import subprocess
from urllib.parse import quote, urlsplit
from urllib.request import url2pathname
import uuid
import unicodedata
from functools import cached_property
from collections import OrderedDict
import threading
from pathlib import Path


def read(path):
    return json.loads(Path(path).read_text('utf-8-sig'))


def digest(text):
    return hashlib.sha256(text.encode('utf-8')).hexdigest()


def quote_key(text):
    # A comma or terminal period in a transcript is not a new saying.
    normalized=unicodedata.normalize('NFKC',text).casefold()
    return re.sub(r'[\s,，。.!！？?、;；：:…]+','',normalized)

def blocked(edits,text):
    key=quote_key(text)
    return any(quote_key(r['text'])==key for r in edits['rejected'].values())

def atomic(path, text):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name('.' + uuid.uuid4().hex + '.tmp')
    try:
        with tmp.open('x', encoding='utf-8', newline='\n') as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(tmp, path)
    finally:
        tmp.unlink(missing_ok=True)


class PersonalLibrary:
    _watches = OrderedDict()
    _watch_lock = threading.Lock()
    def __init__(self, profile=None):
        self.profile = profile if isinstance(profile, dict) else read(profile or Path.home()/'.config/yl-toolbox/profile.json')
        self.root = Path(self.profile['knowledge_root']).resolve()
        self.manifest = Path(self.profile['retrieval']['manifest'])
        self.store = self.root/'90_系统资料/YL知识管理/正文与金句'
        self.store.mkdir(parents=True, exist_ok=True)
        self.expressions = self.root/'04_表达资产/09_金句列表'
        self.state = self.store/'编辑记录.json'
        self.pending = self.store/'待完成事务.json'
        self.catalog = self.root/'02_我的作品全集/本人校订正文'
        self._body_cache = {}

    @cached_property
    def retrieval(self):
        script = Path(self.profile.get('core_root', ''))/'yl-knowledge-search/scripts/retrieval.py'
        spec = importlib.util.spec_from_file_location('personal_library_retrieval', script)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        return mod

    @contextlib.contextmanager
    def locked(self):
        db = sqlite3.connect(self.store/'写入锁.sqlite3', timeout=30)
        try:
            db.execute('BEGIN IMMEDIATE')
            if self.pending.exists():
                self._finish(read(self.pending))
            self._body_cache = {}
            yield
            db.commit()
        finally:
            db.close()

    def _finish(self, plan):
        for name, text in plan['files']:
            p = Path(name).resolve()
            if p not in (self.state.resolve(), self.manifest.resolve(), (self.expressions/'当前金句.md').resolve()) and p.parent != self.catalog.resolve():
                raise ValueError('事务文件不在正文范围内')
            atomic(p, text)
        self.pending.unlink(missing_ok=True)

    def _commit(self, files):
        plan = {'files': [(str(path), text) for path, text in files]}
        atomic(self.pending, json.dumps(plan, ensure_ascii=False))
        self._finish(plan)

    def edits(self):
        return read(self.state) if self.state.exists() else {'added': {}, 'rejected': {}, 'removed': {}, 'edited': {}}

    def active_sources(self, only=None):
        result = {}
        for row in read(self.manifest)['sources']:
            if only is not None and row['source_id'] != only:
                continue
            if row.get('authorship') != 'user_owned' or row.get('kind') in ('source_alias','navigation','external_reference','production_reference','agent_reference','agent_derived_manual','agent_handbook','derived_manual','derived_course_material','project_entry'):
                continue
            if self.retrieval.source_allowed(row, self.profile, self.root)[0]:
                result[row['source_id']] = row
        return result

    def _body(self, row):
        sid = row['source_id']
        p = Path(row['path'])
        stamp=p.stat()
        cache_key=(sid,str(p),stamp.st_size,stamp.st_mtime_ns,json.dumps([row.get(k) for k in ('allowed_spans','include_sections','exclude_sections')],ensure_ascii=False))
        if cache_key in self._body_cache:
            return self._body_cache[cache_key]
        raw = p.read_text('utf-8-sig')
        head = raw.split('---', 2)[1] if raw.startswith('---') else ''
        if any(x.split(':')[-1] in head for x in self.profile.get('excluded_source_ids', [])):
            raise ValueError('来源已排除')
        blocks = list(self.retrieval.paragraphs(raw, row))
        item = {'source_id':sid,'title':row['title'],'path':str(p),'hash':digest(raw),'blocks':blocks,
                'text':'\n\n'.join(b['text'] for b in blocks)}
        if p.parent.resolve()==self.catalog.resolve():
            item['text']=raw.partition('\n')[2].strip()
        self._body_cache[cache_key] = item
        return item

    def get_work(self, source_id):
        row = self.active_sources().get(source_id)
        if row is None:
            raise ValueError('当前知识库没有这份可用的本人正文')
        return self._body(row)

    def _legacy(self):
        path = self.expressions/'历次出处.md'
        if not path.is_file(): return {}
        raw = path.read_text('utf-8-sig')
        result = {}
        for m in re.finditer(r'^## (J\d+)\s*\n(.*?)(?=^## |\Z)', raw, re.M|re.S):
            label, part = m.groups()
            text = re.search(r'^> (.+)$',part,re.M)
            if not text: continue
            refs = []
            for w in re.finditer(r'^- 「(.*?)」 · \[\[([^#|\]]+)(?:#[^|\]]+)?\|([^\]]+)\]\]',part,re.M):
                line = re.search(r' · L(\d+)',w[3])
                refs.append((w[1],str((self.root/(w[2]+('.md' if not w[2].endswith('.md') else ''))).resolve()),int(line[1]) if line else 0))
            result[label]={'id':label,'text':text[1].strip(),'status':'historical','refs':refs}
        return result

    def _find(self, body, text, start=0):
        hits=[]
        for b in body['blocks']:
            pos=0
            while (idx:=b['text'].find(text,pos)) >= 0:
                line=b['start']+b['text'][:idx].count('\n')
                if not start or line==start:
                    hits.append({'source_id':body['source_id'],'source_hash':body['hash'],'start_line':line,
                                 'end_line':line+text.count('\n'),'context':b['text'],'source_title':body['title']})
                pos=idx+len(text)
        return hits

    def _resolve(self, item, sources, paths):
        text=item['text']
        candidates = ([(text,item['source_id'],item.get('start_line',0))] if 'source_id' in item else
                      [(t,sid,n) for t,path,n in item.get('refs',[]) for sid in paths.get(os.path.normcase(path),[])])
        for variant,sid,start in candidates:
            if variant!=text or sid not in sources: continue
            try: body=self._body(sources[sid])
            except (ValueError,OSError): continue
            hits=self._find(body,text,start)
            if not hits:
                hits=self._find(body,text)
                if len(hits)!=1:continue
            if hits:return {**hits[0],'id':item['id'],'text':text,'status':'verified'}
        return None

    def _source_paths(self,sources):
        result={}
        for sid,r in sources.items():
            result.setdefault(os.path.normcase(str(Path(r['path']).resolve())),[]).append(sid)
        return result

    def _suggestions(self, edits):
        return edits.get('suggested',{})

    def _all_quotes(self,edits):
        live={**self._suggestions(edits),**edits['added']}
        texts={quote_key(q['text']) for q in live.values()}
        history={k:q for k,q in self._legacy().items() if quote_key(q['text']) not in texts}
        return {**history,**live}

    def _project_quotes(self, edits, manifest=None):
        # Preserve the original numbered list as the historical view. This live list is regenerated.
        rows=['# 当前金句','','[打开金句管理，可补收、移除或回原文](obsidian://yl-knowledge-workbench?view=quotes)','','[[04_表达资产/09_金句列表/金句列表|历史编号与历次出处]]','','手选和从正文发现的候选均可回查。移除某句后，两个工作台和本页同时隐藏。','']
        registered={r['source_id']:r for r in (manifest or read(self.manifest))['sources']}
        for key,item in self._all_quotes(edits).items():
            if blocked(edits,item['text']):continue
            text=item['text'].replace('\n',' ')
            if key in edits['added'] or key in self._suggestions(edits):
                label='亲选' if key in edits['added'] else '待选'
                source=registered.get(item['source_id'],{})
                if not source.get('index',True):continue
                path=Path(source['path']) if source.get('path') else None
                line='L'+str(item['start_line'])
                if path and path.is_relative_to(self.root):
                    row='[['+path.relative_to(self.root).with_suffix('').as_posix()+'|'+source['title']+' · '+line+']]'
                elif path:
                    row='['+source['title']+' · '+line+']('+path.as_uri()+')'
                else:row=item['source_id']+' · '+line
                rows.append(f"- **{label}**　{text}　（{row}）")
            else:
                rows.append(f"- [[04_表达资产/09_金句列表/历次出处#{key}|{key}]]　{text}")
        return '\n'.join(rows)+'\n'

    def _quote_commit(self, edits):
        files=[(self.state,json.dumps(edits,ensure_ascii=False,indent=2)),(self.expressions/'当前金句.md',self._project_quotes(edits))]
        self._commit(files)
        self._refresh_topics()

    def _suggest(self,items,sources,edits):
        if not isinstance(items,list) or len(items)>1000:raise ValueError('候选批次格式错误')
        imported=[]; withheld=[]; merged=[]
        for candidate in items:
            text=str(candidate.get('text','')).strip(); sid=candidate.get('source_id')
            if not (2<=len(text)<=4000) or blocked(edits,text):continue
            if sid not in sources:
                reason='来源归属或本人片段尚未核准'
                withheld.append({'source_id':sid,'start_line':candidate.get('start_line'),'reason':reason})
                edits.setdefault('deferred',{})[digest(text)]={**withheld[-1],'response_id':candidate.get('response_id','')}
                continue
            hits=self._find(self._body(sources[sid]),text,int(candidate.get('start_line') or 0))
            if len(hits)!=1:
                withheld.append({'source_id':sid,'start_line':candidate.get('start_line'),'reason':'原句或位置未唯一匹配'})
                edits.setdefault('deferred',{})[digest(text)]={**withheld[-1],'response_id':candidate.get('response_id','')};continue
            qid='Q-'+digest(text)[:16]
            contexts=candidate.get('contexts',[])
            if not isinstance(contexts,list):raise ValueError('使用场景须为列表')
            entry={'id':qid,'text':text,'source_id':sid,'source_hash':hits[0]['source_hash'],'start_line':hits[0]['start_line'],'status':'candidate','origin':'source_extraction','topic':str(candidate.get('topic',''))[:160],'contexts':[str(x)[:200] for x in contexts[:12]]}
            entry['response_id']=str(candidate.get('response_id',''))
            existing=next((v for v in [*edits['added'].values(),*self._suggestions(edits).values()] if quote_key(v['text'])==quote_key(text)),None)
            if existing:
                ref={k:entry[k] for k in ('source_id','source_hash','start_line','text','response_id')}
                if ref['source_id']!=existing['source_id'] or ref['start_line']!=existing['start_line']:
                    alts=existing.setdefault('variants',[])
                    if ref not in alts:alts.append(ref)
                existing['contexts']=list(dict.fromkeys(existing.get('contexts',[])+entry['contexts']))
                if entry['topic']!=existing.get('topic'):
                    existing['related_topics']=list(dict.fromkeys(existing.get('related_topics',[])+[entry['topic']]))
                merged.append(existing['id'])
            else:
                edits.setdefault('suggested',{})[qid]=entry;imported.append(qid)
        if imported or withheld or merged:self._quote_commit(edits)
        return {'ok':True,'accepted':imported,'merged':merged,'withheld':withheld}

    def verified_quotes(self, only_direct=False):
        with self.locked():
            edits=self.edits(); sources=self.active_sources(); paths=self._source_paths(sources)
            out=[]
            items={**self._suggestions(edits),**edits['added']} if only_direct else self._all_quotes(edits)
            for item in items.values():
                if blocked(edits,item['text']): continue
                resolved=self._resolve(item,sources,paths)
                if resolved:
                    resolved['origin']='hand_selected' if item['id'] in edits['added'] else ('source_extraction' if item['id'] in self._suggestions(edits) else 'legacy')
                    resolved.update(topic=item.get('topic',''),contexts=item.get('contexts',[]))
                    if resolved['origin']=='source_extraction':resolved['status']='candidate'
                    out.append(resolved)
            return out

    def watch_files(self, item_key, files=None):
        key=(str(self.root),item_key)
        with self._watch_lock:
            if files is not None:
                self._watches[key]=tuple(dict.fromkeys(files))
                self._watches.move_to_end(key)
                if len(self._watches)>512:self._watches.popitem(last=False)
            return self._watches.get(key,())

    def revision(self, watch=()):
        def stamp(p):
            try:
                st=Path(p).stat()
                return str(st.st_mtime_ns)+'-'+str(st.st_size)
            except FileNotFoundError:return '-'
        files=(self.state,self.manifest,self.root/'01_我的思想体系/思想地图导读.md',self.root/'01_我的思想体系/按话题读作品.md',self.expressions/'历次出处.md',self.store/'四域归类.json')
        return {'global':'|'.join(map(stamp,files)), 'detail':'|'.join(map(stamp,watch))}

    def dispatch(self, req, include_watch_files=False):
        action=req.get('action','')
        if action=='library.revision':
            return {'ok':True,'revision':self.revision(self.watch_files(str(req.get('watch',''))))}
        with self.locked():
            reading_watch=[]
            result=self._dispatch(req, reading_watch=reading_watch) if action=='works.get' else self._dispatch(req)
            watch=()
            if action in ('works.get','quotes.source'):
                item=result['item']
                ids={item.get('source_id'),*(v.get('source_id') for v in item.get('variants',[]))}
                watch=list(dict.fromkeys(str(p) for p in (
                    *(v['path'] for v in self._body_cache.values() if v['source_id'] in ids),
                    *reading_watch,
                )))
                key='works:'+item['source_id'] if action=='works.get' else 'quotes:'+item['id']
                self.watch_files(key,watch)
                if include_watch_files:result['_watch']={'key':key,'files':list(dict.fromkeys(watch))}
            result['revision']=self.revision(watch)
            return result

    def _dispatch(self, req, *, reading_watch=None):
        action=req['action']
        if action=='library.catalog':
            from library_browse import catalog
            return {'ok':True,'item':catalog(self)}
        if action=='works.get':
            from library_browse import readable_blocks
            from reading_info import merge_metrics, publication_data, reading_info
            sid=str(req.get('source_id',''))
            sources=self.active_sources(only=sid)
            if sid not in sources:raise ValueError('来源已移除或不可用')
            row=sources[sid]
            item=self._body(row)
            info=reading_info(item,row,root=self.root)
            ledger, files=publication_data(self.root,item,row,with_watch=reading_watch is not None,profile=self.profile)
            if reading_watch is not None:
                reading_watch.extend(files)
            info['metrics']=merge_metrics(info['metrics'],ledger)
            return {'ok':True,'item':{**item,'readable_blocks':readable_blocks(item),'reading_info':info}}
        if action=='map.get':
            p=self.root/'01_我的思想体系/思想地图导读.md'
            return {'ok':True,'item':self._map(p)}
        edits=self.edits()
        sources=self.active_sources()
        sid=str(req.get('source_id',''))
        if action=='works.list':
            items=[{'source_id':k,'title':r['title']} for k,r in sources.items()]
            return self.page(items,req)
        if action in ('works.save','works.remove'):
            return self._work_change(req,action,sid,sources,edits)
        if action=='quotes.suggest':return self._suggest(req.get('items'),sources,edits)
        quotes=self._all_quotes(edits)
        if action=='quotes.list':
            # Keep the author's selections and source-linked candidates reachable on the first page.
            suggestions = self._suggestions(edits)
            def reading_order(item):
                if item[0] in edits['added']:
                    return 0
                return 1 if item[0] in suggestions else 2
            ordered = sorted(quotes.items(), key=reading_order)
            page=self.page([{'id':i,'text':v['text'],'status':v.get('status','verified'),'topic':v.get('topic',''),'contexts':v.get('contexts',[])} for i,v in ordered
                            if not blocked(edits,v['text']) and ('source_id' not in v or v['source_id'] in sources)],req)
            paths=self._source_paths(sources)
            for item in page['items']:
                resolved=self._resolve(quotes[item['id']],sources,paths)
                item['status']=('candidate' if quotes[item['id']].get('status')=='candidate' else 'verified') if resolved else 'historical'
            return page
        if action=='quotes.add':
            text=str(req.get('text','')).strip()
            if len(text)<2 or len(text)>4000:raise ValueError('请选择正文中连续的 2 至 4000 个字符')
            key=digest(text)
            if blocked(edits,text) and req.get('restore') is not True:raise ValueError('这句曾被移除。要恢复，请明确选择恢复。')
            if sid not in sources:raise ValueError('来源不可用')
            body=self._body(sources[sid])
            if req.get('expected_hash') is not None and req['expected_hash']!=body['hash']:
                raise ValueError('正文已变化，请核对新版本后再补收')
            hits=self._find(body,text,int(req.get('start_line') or 0))
            if len(hits)!=1:raise ValueError('请选取正文中可唯一定位的原句，重复原句请补充所在行')
            preferred='Q-'+key[:16]
            fresh=preferred if preferred in quotes else next((q['id'] for q in quotes.values() if q['text']==text),preferred)
            item={'id':fresh,'text':text,'source_id':sid,'start_line':hits[0]['start_line'],'source_hash':body['hash'],'status':'verified'}
            selected=quotes.get(fresh,{})
            for field in ('contexts','topic','related_topics','variants','response_id'):
                if field in selected:item[field]=selected[field]
            edits['added'][fresh]=item
            edits['rejected']={k:v for k,v in edits['rejected'].items() if quote_key(v['text'])!=quote_key(text)}
        elif action in ('quotes.remove','quotes.source'):
            item=quotes.get(str(req.get('id','')))
            if not item: raise ValueError('没有找到金句')
            key=digest(item['text'].strip())
            if action=='quotes.source':
                if key in edits['rejected']:raise ValueError('金句已移除')
                paths=self._source_paths(sources)
                resolved=self._resolve(item,sources,paths)
                if resolved:
                    alternates=[]
                    for v in item.get('variants',[]):
                        other=self._resolve({'id':item['id'],**v},sources,paths)
                        if other:alternates.append(other)
                    resolved['variants']=alternates
                    if item.get('status')=='candidate':resolved.update(status='candidate',topic=item['topic'],contexts=item['contexts'])
                    return {'ok':True,'item':resolved}
                for variant,path,line in item.get('refs',[]):
                    for sid in paths.get(os.path.normcase(path),[]):
                        candidate=self._resolve({'id':item['id'],'text':variant,'source_id':sid,'start_line':line},sources,paths)
                        if candidate:return {'ok':True,'item':{**candidate,'status':'variant','representative':item['text']}}
                return {'ok':True,'item':{'id':item['id'],'text':item['text'],'status':'unverified','context':'现有可用正文中尚未定位到原句。'}}
            edits['rejected'][key]={'id':item['id'],'text':item['text']}
        else: raise ValueError('未知资料操作')
        self._quote_commit(edits)
        return {'ok':True,'item':{k:v for k,v in item.items() if k!='refs'}}

    @staticmethod
    def page(items,req):
        query=str(req.get('q','')).casefold()
        matches=[x for x in items if any(query in str(v).casefold() for v in x.values())]
        offset=max(0,int(req.get('offset',0))); limit=max(1,min(300,int(req.get('limit',40))))
        return {'ok':True,'total':len(matches),'items':matches[offset:offset+limit]}

    def _map(self, path):
        sources=self.active_sources()
        by_path={os.path.normcase(os.path.abspath(row['path'])):sid for sid,row in sources.items()}
        def source_id(p):
            return by_path.get(os.path.normcase(os.path.abspath(p)))
        topics=path.with_name('按话题读作品.md')
        domains=[]; counts={}; summary=[]; domain=None; question=None
        if topics.is_file():
            for line in topics.read_text('utf-8-sig').splitlines():
                entry=re.fullmatch(r'- \[\[#([^|]+)\|[^\]]+\]\]\s+(\d+) 份材料',line)
                if entry:
                    counts[entry[1]]=int(entry[2]);continue
                if line.startswith('## '):
                    title=line[3:]
                    domain=None if title=='从领域开始' else {'title':title,'count':counts.get(title),'questions':[]}
                    if domain:domains.append(domain)
                    question=None
                elif domain and line.startswith('### '):
                    question={'title':line[4:],'refs':[]}
                    domain['questions'].append(question)
                elif question and re.fullmatch(r'\d+ 份材料。',line):
                    question['count']=int(line.partition(' ')[0])
                elif question:
                    ref=re.fullmatch(r'(?:> )?- \[\[([^|]+)\|(.+?)\]\]（第 (\d+) 行）',line)
                    if ref:
                        relative=ref[1].partition('#')[0]
                        target=self.root/(relative+'.md')
                    else:
                        ref=re.fullmatch(r'(?:> )?- \[(.+?)\]\(<(file:[^>]+)>\)（第 (\d+) 行）',line)
                        if not ref:continue
                        target=Path(url2pathname(urlsplit(ref[2]).path))
                    sid=source_id(target)
                    question['refs'].append({'source_id':sid,'title':sources[sid]['title'] if sid else target.stem,'line':int(ref[3])})
                elif line.startswith(('本页读取','按同一原段')):
                    summary.append(line)
        parts=[]
        guide = path.read_text('utf-8-sig') if path.is_file() else ''
        for line in guide.splitlines():
            if line.startswith(('# ', '## ')):
                parts.append({'title':line.lstrip('# ').strip(),'paragraphs':[]})
            elif line.strip() and parts and not line.startswith('|---'):
                cells=[]
                last=0
                for m in re.finditer(r'\[\[([^\]]+)\]\]',line):
                    cells.append({'label':line[last:m.start()].strip('|').replace('**','')})
                    target,_,label=m[1].replace('\\|','|').partition('|')
                    rel,_,heading=target.partition('#')
                    if not rel: rel=path.relative_to(self.root).as_posix()
                    uri='obsidian://open?vault='+quote(self.root.name,safe='')+'&file='+quote(rel+('#'+heading if heading else ''),safe='')
                    cells.append({'label':label or target,'uri':uri,'source_id':source_id(self.root/(rel+'.md')),'section':heading});last=m.end()
                cells.append({'label':line[last:].strip('|').replace('**','')})
                parts[-1]['paragraphs'].append(cells)
        return {'title':'思想地图导读','parts':parts,'domains':domains,'summary':summary}

    def publish_discovery(self, manifest):
        # Scanner output is rebuilt from scratch. Reapply the user's decisions under the shared lock.
        with self.locked():
            updates=self.edits().get('source_overrides',{})
            keyed={r['source_id']:r for r in manifest['sources']}
            for sid,saved in updates.items():
                discovered=keyed.get(sid)
                if discovered and (not discovered.get('index',True) or discovered.get('authorship') not in ('user_owned',None)):
                    if saved.get('index',True):
                        continue
                keyed[sid]=saved
                for duplicate in list(keyed):
                    if duplicate!=sid and Path(keyed[duplicate]['path']).resolve()==Path(saved['path']).resolve():
                        keyed.pop(duplicate)
            manifest['sources']=sorted(keyed.values(),key=lambda r:r['source_id'])
            atomic(self.manifest,json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')
        return manifest

    def _new_candidates(self, row, raw, edits):
        # Cue words identify lines to review. A human decision is required for adoption.
        sid=row['source_id']; blocks=list(self.retrieval.paragraphs(raw,row))
        queue=edits.setdefault('quote_review',{})
        queue[sid]={'hash':digest(raw),'status':'awaiting_selection','blocks':len(blocks)}
        suggestions=edits.setdefault('suggested',{})
        found=0
        for block in blocks:
            for hit in re.finditer(r'[^。！？!?\n]+[。！？!?]',block['text']):
                text=hit[0].strip()
                if not 12<=len(text)<=140 or not re.search(r'不是.{1,65}(?:而是|是)|越.{1,26}越|只有.{1,35}才|与其.{1,40}不如|流水的|就像|相当于',text):continue
                if re.search(r'据说|他说|她说|引自|摘自|引用|[「『“”]',text):continue
                if blocked(edits,text):continue
                qid='Q-'+digest(text)[:16]
                if any(quote_key(q['text'])==quote_key(text) for q in [*suggestions.values(),*edits['added'].values()]):continue
                line=block['start']+block['text'][:hit.start()].count('\n')
                suggestions[qid]={'id':qid,'text':text,'source_id':sid,'start_line':line,'source_hash':digest(raw),'status':'candidate','origin':'source_extraction','topic':row['title'],'contexts':[],'extraction_method':'local_review_cue'}
                found+=1
                if found>=2:break
            if found>=2:break
        queue[sid]['local_candidates']=found

    @staticmethod
    def clean_blocks(blocks, corrections):
        # A free-form editor can change a draft; unattended ingestion may only apply anchored corrections.
        allowed={'错字','识别错误','转录拼接','无关环境声','确认无关的旁人串话'}
        by_line={}
        for correction in corrections:
            if correction.get('kind') not in allowed or not str(correction.get('before','')):
                raise ValueError('校订项需说明可确认的错误及原字句')
            by_line.setdefault(int(correction['line']),[]).append(correction)
        paragraphs=[];changes=[]
        for block in blocks:
            lines=[]
            for line_no,original in enumerate(block['text'].splitlines(),block['start']):
                value=original
                if original.strip() in {'[环境噪声]','[环境噪音]','[麦克风杂音]','[录音设备噪声]','【环境噪声】','【环境噪音】'}:
                    changes.append({'line':line_no,'kind':'无关环境声','before':original,'after':''})
                    value=''
                for change in by_line.pop(line_no,[]):
                    old=change['before'];new=change.get('after','')
                    if '\n' in old or '\n' in new or value.count(old)!=1:
                        raise ValueError('校订位置与原字句未唯一匹配')
                    value=value.replace(old,new)
                    changes.append(dict(change))
                if value:lines.append(value)
            if lines:paragraphs.append('\n'.join(lines))
        if by_line:raise ValueError('校订落在可用正文范围之外')
        return '\n\n'.join(paragraphs),changes

    def register(self, req):
        # CLI-only ingestion, for adapters that have reviewed ownership and source spans.
        if req.get('authorship')!='user_owned':raise ValueError('须先核准本人正文归属')
        with self.locked():
            manifest=read(self.manifest); edits=self.edits(); sid=str(req.get('source_id','')).strip()
            if not sid or len(sid)>300:raise ValueError('缺少稳定来源 ID')
            if sid in edits['removed']:raise ValueError('来源已由本人移除')
            path=Path(req['source_path']).resolve()
            row={'path':str(path),'source_id':sid,'authorship':'user_owned','kind':'work','title':str(req['title']).strip(),'include_sections':req.get('include_sections',[]),'exclude_sections':req.get('exclude_sections',[]),'index':True,'review_status':'owner_text_registered','quote_ready':False}
            if 'allowed_spans' in req:row['allowed_spans']=req['allowed_spans']
            if not self.retrieval.source_allowed(row,self.profile,self.root)[0]:raise ValueError('原件不在允许的来源范围')
            raw=path.read_text('utf-8-sig')
            if req.get('source_sha256')!=hashlib.sha256(path.read_bytes()).hexdigest():raise ValueError('原件哈希已变化，请回查')
            source=self._body(row)
            cleaned,changes=self.clean_blocks(source['blocks'],req.get('corrections',[]))
            files=[]
            if not source['text']:raise ValueError('允许范围内没有正文')
            previous=next((r for r in manifest['sources'] if r['source_id']==sid),None)
            if previous and (previous.get('authorship')!='user_owned' or not previous.get('index',True)):raise ValueError('既有来源归属或授权待核')
            if previous and Path(previous['path']).resolve()!=path and edits.get('edited',{}).get(sid,{}).get('original_path')!=str(path):
                raise ValueError('来源 ID 已指向其他原件，请核实版本关系')
            if previous and Path(previous['path']).parent.resolve()==self.catalog.resolve():
                saved=edits['edited'].get(sid,{})
                if saved.get('original_hash')==source['hash'] and saved.get('corrections')==changes:
                    current=Path(previous['path']).read_text('utf-8-sig')
                    return {'ok':True,'item':{'source_id':sid,'hash':digest(current),'text_length':len(current.partition('\n')[2].strip()),'corrections':len(changes)}}
                if req.get('expected_hash')!=digest(Path(previous['path']).read_text('utf-8-sig')):
                    raise ValueError('已有较新的校订正文，请先回读并提供 expected_hash 后再登记修订')
            if previous:
                if previous.get('allowed_spans') not in (None,row.get('allowed_spans')) or any(previous.get(k) and previous[k]!=row.get(k) for k in ('include_sections','exclude_sections')):raise ValueError('不得放宽既有正文范围')
            if changes:
                if not cleaned.strip():raise ValueError('清除噪声后缺少本人正文')
                location=self.catalog/(digest(sid)[:24]+'.md')
                raw='# '+row['title']+'\n\n'+cleaned+'\n'
                edits['edited'][sid]={'original_path':str(path),'original_hash':source['hash'],'corrections':changes}
                row.update(path=str(location),include_sections=[],exclude_sections=[],review_status='corrected_from_source')
                row.pop('allowed_spans',None);files.append((location,raw))
            if previous:previous.update(row)
            else:manifest['sources'].append(row)
            edits.setdefault('source_overrides',{})[sid]=dict(previous or row)
            self._new_candidates(row,raw,edits)
            self._commit(files+[(self.state,json.dumps(edits,ensure_ascii=False,indent=2)),(self.manifest,json.dumps(manifest,ensure_ascii=False,indent=2)+'\n'),(self.expressions/'当前金句.md',self._project_quotes(edits,manifest))])
            self._refresh_topics()
            return {'ok':True,'item':{'source_id':sid,'hash':digest(raw),'text_length':len(cleaned),'corrections':len(changes)}}

    def _work_change(self,req,action,sid,sources,edits):
        manifest=read(self.manifest); files=[]
        row=next((r for r in manifest['sources'] if r['source_id']==sid),None)
        if sid:
            if sid not in sources or not row:raise ValueError('来源已移除或不可编辑')
            old=self._body(sources[sid])
            if req.get('expected_hash')!=old['hash']:raise ValueError('正文已变化，请刷新后再修改')
        if action=='works.remove':
            if not sid:raise ValueError('缺少正文来源')
            row['index']=False; row['reason']='removed_by_owner'
            edits['removed'][sid]={'path':row['path'],'title':row['title']}
            item={'source_id':sid,'title':row['title']}
        else:
            title=str(req.get('title','')).strip(); text=str(req.get('text','')).strip()
            if not title or '\n' in title or len(title)>200 or not text or len(text)>1000000:raise ValueError('请填写标题和一百万字符以内的校订正文')
            if not sid:
                sid='PERSONAL-'+digest(title+'\0'+text)[:20]
                if sid in edits['removed']:raise ValueError('该正文已移除')
                if sid in sources:return {'ok':True,'item':self._body(sources[sid])}
                # Reuse an already registered identical body, including a differently titled copy.
                for existing in sources.values():
                    try: previous=self._body(existing)
                    except (OSError,ValueError):continue
                    if previous['text'].strip()==text:return {'ok':True,'item':previous}
                row={'source_id':sid,'kind':'work','authorship':'user_owned','aliases':[]}
                manifest['sources'].append(row)
            location=self.catalog/(digest(sid)[:24]+'.md')
            raw='# '+title+'\n\n'+text+'\n'
            # A literal heading in the user's text is part of Markdown. Headings remain navigable.
            if sid not in edits['edited'] and row.get('path'):
                edits['edited'][sid]={'original_path':row['path'],'original_hash':old['hash']}
            row.update(path=str(location),title=title,index=True,include_sections=[],exclude_sections=[],review_status='owner_corrected',quote_ready=False)
            row.pop('allowed_spans',None)
            self._new_candidates(row,raw,edits)
            files.append((location,raw));item={'source_id':sid,'title':title,'hash':digest(raw)}
        edits.setdefault('source_overrides',{})[sid]=dict(row)
        files.append((self.expressions/'当前金句.md',self._project_quotes(edits,manifest)))
        files.extend([(self.state,json.dumps(edits,ensure_ascii=False,indent=2)),(self.manifest,json.dumps(manifest,ensure_ascii=False,indent=2)+'\n')])
        self._commit(files)
        self._refresh_topics()
        return {'ok':True,'item':item}

    def _refresh_topics(self):
        # Only the machine owner's external profile can authorize executable code.
        config=Path.home()/'.config/yl-toolbox/profile.json'
        try:
            owner=read(config)
        except (ValueError,OSError): return
        if not isinstance(owner,dict): return
        selected=owner.get('local_hooks',{}).get('workbench_topic_refresh',{})
        if not isinstance(selected,dict) or not isinstance(selected.get('script'),str): return
        if not owner.get('knowledge_root') or Path(owner['knowledge_root']).resolve()!=self.root: return
        script=Path(selected['script'])
        if not script.is_absolute() or script.suffix.lower()!='.py' or not script.is_file(): return
        subprocess.Popen([sys.executable,'-B',str(script),'--vault',str(self.root)],
                         stdin=subprocess.DEVNULL,stdout=subprocess.DEVNULL,stderr=subprocess.DEVNULL,
                         creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))


if __name__=='__main__':
    try:
        req=json.loads(sys.stdin.buffer.read().decode('utf-8-sig'))
        lib=PersonalLibrary(sys.argv[2]) if len(sys.argv)==3 and sys.argv[1]=='--profile' else PersonalLibrary()
        result=lib.register(req) if req.get('action')=='works.register' else lib.dispatch(req,include_watch_files=True)
    except (ValueError,KeyError,OSError,sqlite3.Error) as exc:
        result={'ok':False,'error':str(exc)}
    sys.stdout.buffer.write(json.dumps(result,ensure_ascii=False).encode('utf-8'))

