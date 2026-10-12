"""Isolated regression tests: never write into the real vault or call inference."""
import copy, http.client, json, tempfile, threading, time, unittest
from pathlib import Path
from unittest.mock import patch
from server import App, handler, ThreadingHTTPServer, validate_enhancement
from knowledge import Knowledge, sha

class FakeKnowledge:
    def __init__(self,profile):
        self.root=Path(profile); self.nodes={'ATOM-1':{}};self.topics=[]
    def uri(self,path):return 'obsidian://open?file='+Path(path).name
    def evidence(self,*args):return {'nodes':[{'id':'ATOM-1'}],'passages':[{'citation':'S1','source_id':'source-1','source_hash':'abc','node_ids':['ATOM-1']}],'semantic':True,'warnings':[]}
    def verify_evidence(self,evidence):pass

class FakeAstra:
    def __init__(self,result):self.result=result
    def complete(self,*args,**kwargs):return {'text':self.result,'model':'gpt-6-astra'}

def estimate(): return {'tier':'5000','basis':'无可比历史样本，暂估','confidence':'不足','reference_ids':[]}
def original(): return {'message':'使用知识','audience':'创作者','interest':'找到材料','limitation':'缺少实际用途','estimate':estimate()}
def direction():
    return {'title':'一个方向','audience':'个人创作者','expansion':'从找不到资料谈起','promise':'找到可调用的材料','opening':'你积累的经验能不能继续用？','hook_basis':'未找到合适历史例子','structure':['问题','原话','行动'],'word_count':900,'confidence':'一般','goal':'使用知识','risk':'材料不足','scores':{k:3 for k in ('audience','material','promise','distinctiveness','transition')},'node_ids':['ATOM-1'],'citations':['S1'],'estimate':estimate(),'highlights':['亮点一','亮点二','亮点三'],'ending':'让知识接上行动。','conversion':{'goal':'留言','copy':'你最想解决什么？','path':'根据留言选择下一期'}}

class WorkbenchTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.root=Path(self.tmp.name)
        with patch('server.Knowledge',FakeKnowledge):self.app=App(self.root,self.root/'runtime')
    def tearDown(self):self.tmp.cleanup()
    def wait(self,result):
        for _ in range(150):
            job=self.app.job_state(result['job_id'])
            if job['status'] in ('completed','failed'):return job
            time.sleep(.02)
        self.fail('fixture job timed out')
    def make_idea(self):return self.app.save_idea({'text':'知识库管理的终极目的是使用。','attribution':'personal'})['id']
    def analyze(self,ident):
        self.app.astra=FakeAstra(json.dumps({'original':original(),'core':'使用知识','directions':[direction(),direction()],'note':'编辑判断'},ensure_ascii=False))
        return self.wait(self.app.analyze({'id':ident}))
    def test_enhancement_rejects_fake_tier_and_history(self):
        analysis={'original':original(),'directions':[direction(),direction()]}
        analysis['directions'][0]['estimate']['tier']='100万'
        with self.assertRaises(ValueError): validate_enhancement(analysis,set())
        analysis['directions'][0]['estimate']=estimate()
        analysis['directions'][0]['estimate']['reference_ids']=['invented']
        with self.assertRaises(ValueError): validate_enhancement(analysis,set())
    def test_enhancement_requires_distinct_highlights(self):
        analysis={'original':original(),'directions':[direction(),direction()]}
        analysis['directions'][0]['highlights']=['重复','重复','重复']
        with self.assertRaises(ValueError): validate_enhancement(analysis,set())
    def test_reanalysis_preserves_prior_version(self):
        ident=self.make_idea();self.analyze(ident);self.app.select({'id':ident,'index':0});self.analyze(ident)
        with self.app.db() as db:
            row=db.execute('select * from analysis_versions where idea_id=?',(ident,)).fetchone()
            self.assertEqual(row['selected'],0)
            self.assertIsNotNone(row['analysis'])
    def test_original_persists_and_deduplicates(self):
        ident=self.make_idea(); result=self.app.save_idea({'text':'知识库管理的终极目的是使用。'})
        self.assertEqual(result,{'id':ident,'duplicate':True})
        self.assertEqual(self.app.idea(ident)['text'],'知识库管理的终极目的是使用。')
        self.assertEqual(len(list((self.root/'03_选题库/灵感').glob('*.md'))),1)
    def test_attribution_separates_external(self):
        self.make_idea(); self.app.save_idea({'text':'知识库管理的终极目的是使用。','attribution':'external'})
        self.assertEqual(len(self.app.list_ideas()),2)
    def test_direction_and_draft_workflow(self):
        ident=self.make_idea();self.assertEqual(self.analyze(ident)['status'],'completed')
        self.app.select({'id':ident,'index':0});self.app.astra=FakeAstra('# 初稿\n\n知识要能使用。[S1]')
        self.assertEqual(self.wait(self.app.draft({'id':ident}))['status'],'completed')
        row=self.app.idea(ident); self.assertEqual(row['status'],'drafted');self.assertTrue(Path(row['draft_path']).exists())
        self.app.select({'id':ident,'index':1});self.assertIsNone(self.app.idea(ident)['draft_path'])
        self.assertEqual(len(list((self.root/'02_我的作品全集/工作台草稿').glob('*.md'))),1)
    def test_invalid_selection(self):
        ident=self.make_idea();self.analyze(ident)
        for i in (-1,2,True,'0'):
            with self.assertRaises(ValueError):self.app.select({'id':ident,'index':i})
    def test_rejects_invented_analysis_source(self):
        ident=self.make_idea();bad=direction();bad['citations']=['S999']
        self.app.astra=FakeAstra(json.dumps({'core':'x','directions':[bad,bad]}))
        self.assertEqual(self.wait(self.app.analyze({'id':ident}))['status'],'failed')
        self.assertIsNone(self.app.idea(ident)['analysis'])
    def test_rejects_invented_draft_source(self):
        ident=self.make_idea();self.analyze(ident);self.app.select({'id':ident,'index':0})
        self.app.astra=FakeAstra('不真实的引用 [S999]')
        self.assertEqual(self.wait(self.app.draft({'id':ident}))['status'],'failed')
        self.assertIsNone(self.app.idea(ident)['draft_path'])
    def test_rejects_invented_chat_source(self):
        self.app.astra=FakeAstra('错误的依据 [S999]')
        self.assertEqual(self.wait(self.app.chat({'question':'如何使用知识？'}))['status'],'failed')
        self.assertEqual([m['role'] for m in self.app.history()],['user'])
    def test_read_source_requires_allowlist(self):
        k=Knowledge.__new__(Knowledge);k.sources={}
        with self.assertRaises(KeyError):k.source('../private')
    def test_evidence_rejects_changed_original(self):
        k=Knowledge.__new__(Knowledge);p=self.root/'source.md';p.write_text('旧原文',encoding='utf-8')
        k.sources={'s':{'path':str(p)}};e={'passages':[{'source_id':'s','source_hash':sha(p.read_bytes())}]}
        k.verify_evidence(e);p.write_text('新原文',encoding='utf-8')
        with self.assertRaises(ValueError):k.verify_evidence(e)
    def test_http_local_boundary_and_encoded_paths(self):
        httpd=ThreadingHTTPServer(('127.0.0.1',0),handler(self.app));thread=threading.Thread(target=httpd.serve_forever,daemon=True);thread.start()
        def request(path,headers):
            conn=http.client.HTTPConnection('127.0.0.1',httpd.server_port)
            conn.request('GET',path,headers=headers);r=conn.getresponse();r.read();conn.close();return r.status
        try:
            self.assertEqual(request('/api/health',{}),200)
            self.assertEqual(request('/api/ideas',{}),403)
            self.assertEqual(request('/%61pi/ideas',{}),403)
            h={'X-Knowledge-Client':'workbench'}
            self.assertEqual(request('/api/ideas',h),200)
            self.assertEqual(request('/api/ideas',{**h,'Origin':'https://evil.example'}),403)
            self.assertEqual(request('/api/ideas',{**h,'Host':'evil.example'}),403)
            self.assertEqual(request('/../server.py',{}),404)
        finally:httpd.shutdown();httpd.server_close();thread.join()

if __name__=='__main__':unittest.main(verbosity=2)
