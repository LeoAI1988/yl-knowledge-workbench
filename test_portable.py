"""Portable-vault contract: isolated files, explicit types, no model calls."""
import json,tempfile,unittest
from pathlib import Path
from markdown_vault import MarkdownVault
from server import App

class PortableTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory();self.base=Path(self.tmp.name)
        self.root=self.base/'vault';self.root.mkdir()
        self.profile=self.base/'profile.json'
        self.profile.write_text(json.dumps({'adapter':'markdown','knowledge_root':str(self.root),'workbench':{'runtime':str(self.base/'state')}}),'utf-8')
    def tearDown(self):self.tmp.cleanup()
    def note(self,name,text):
        p=self.root/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text(text,'utf-8');return p
    def test_empty_vault_and_isolated_runtime(self):
        app=App(self.profile)
        self.assertEqual(app.runtime,self.base/'state')
        self.assertEqual(app.get('/api/bootstrap')['stats']['atoms'],0)
        self.assertIsNone(app.get('/api/bootstrap')['sample_id'])
        self.assertEqual(app.get('/api/library'),{'works':[],'sources':[]})
    def test_only_explicit_types_become_atoms_and_links(self):
        self.note('ordinary.md','# 普通记录\n记录不能被自动当成提炼后的知识。')
        self.note('first.md','---\ntype: OPI\nid: a\ndomains: [经营]\n---\n# 观点甲\n一段思考 [[second]]')
        self.note('second.md','---\ntype: SOL\nid: b\n---\n# 方法乙\n方法正文 [[first]]')
        self.note('words.md','---\ntype: expression\n---\n一段表达 [[first]]')
        self.note('work.md','---\ntype: work\n---\n# 作品\n作品正文 [[first]]')
        k=MarkdownVault(self.profile)
        self.assertEqual(set(k.nodes),{'a','b'});self.assertEqual(k.nodes['b']['domains'],['pending'])
        self.assertEqual([(r['source'],r['target']) for r in k.relations],[('a','b')])
        self.assertEqual(next(iter(k.expressions.values()))['node_ids'],['a'])
        self.assertEqual(len(k.library()['works']),1);self.assertEqual(len(k.library()['sources']),4)
        self.assertEqual(len(k.detail('a')['relations']),1)
        self.assertEqual(k.detail('a')['works'][0]['title'],'作品')
        self.assertIn('作品正文',k.work(k.works[0]['id'])['sections'][0]['text'])
    def test_private_hidden_unindexed_and_invalid_yaml_skipped(self):
        for name,text in {'.obsidian/secret.md':'秘密','80_私人档案/private.md':'秘密','a.md':'---\nprivacy: P2\n---\n秘密','b.md':'---\nindex: false\n---\n秘密','bad.md':'---\ntitle: [\n---\n不可解析','list.md':'---\n- a\n---\n非字典属性'}.items():self.note(name,text)
        self.note('public.md','# 可读\n公开材料')
        k=MarkdownVault(self.profile);self.assertEqual(len(k.sources),1)
        self.assertEqual(k.search('秘密')['passages'],[])
    def test_privacy_change_revokes_stale_source(self):
        p=self.note('public.md','# 可读\n原来可读')
        k=MarkdownVault(self.profile);sid=next(iter(k.sources))
        p.write_text('---\nprivacy: P3\n---\n改为私密','utf-8')
        with self.assertRaises(KeyError):k.source(sid)
    def test_display_identity_can_refresh_without_restart(self):
        app=App(self.profile);config=json.loads(self.profile.read_text('utf-8'))
        config['workbench']['name']='测试助手';self.profile.write_text(json.dumps(config),'utf-8')
        app.post('/api/reload',{})
        self.assertEqual(app.get('/api/bootstrap')['identity']['name'],'测试助手')
    def test_model_and_exclusions_refresh_and_busy_refusal(self):
        self.note('exclude/a.md','# 资料\n不再检索')
        app=App(self.profile);config=json.loads(self.profile.read_text('utf-8'))
        config['workbench'].update(model='test-model',exclude_folders=['exclude'])
        self.profile.write_text(json.dumps(config),'utf-8')
        app.jobs['busy']={'status':'running'}
        with self.assertRaises(ValueError):app.post('/api/reload',{})
        self.assertNotEqual(app.model,'test-model')
        app.jobs.clear();app.post('/api/reload',{})
        self.assertEqual(app.astra.model,'test-model')
        self.assertEqual(len(app.k.sources),0)

if __name__=='__main__':unittest.main()
