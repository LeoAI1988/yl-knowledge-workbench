import json
import os
import tempfile
import unittest
from pathlib import Path
from personal_library import PersonalLibrary


def yl_profile():
    root=os.environ.get('YL_WORKBENCH_TEST_CORE')
    if not root or not (Path(root)/'yl-knowledge-search/scripts/retrieval.py').is_file():
        raise unittest.SkipTest('Set YL_WORKBENCH_TEST_CORE to test the optional YL adapter.')
    return {'core_root':root}


class SharedLibraryTest(unittest.TestCase):
    def test_quote_browsing_pages_author_choices_then_source_candidates_then_history(self):
        base = yl_profile()
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root/'作品.md'
            source.write_text('我亲自选这句。\n\n还有一句值得核对。', encoding='utf-8')
            manifest = root/'manifest.json'
            manifest.write_text(json.dumps({'sources':[{'source_id':'work','path':str(source),
                'title':'作品','kind':'work','authorship':'user_owned'}]}), encoding='utf-8')
            lib = PersonalLibrary(dict(base, knowledge_root=folder, source_roots=[], retrieval={'manifest':str(manifest)}))
            lib.expressions.mkdir(parents=True, exist_ok=True)
            (lib.expressions/'历次出处.md').write_text('## J01\n> 早期收录了一句。\n', encoding='utf-8')
            candidate = lib.dispatch({'action':'quotes.suggest','items':[{'source_id':'work','text':'还有一句值得核对。',
                'start_line':3,'topic':'写作','contexts':['核对']}]})['accepted'][0]
            selected = lib.dispatch({'action':'quotes.add','source_id':'work','text':'我亲自选这句。'})['item']['id']
            def page(offset):
                return lib.dispatch({'action':'quotes.list','offset':offset,'limit':1})['items'][0]['id']
            self.assertEqual([page(i) for i in range(3)], [selected,candidate,'J01'])

    def test_map_without_optional_guide(self):
        base = {}
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            manifest = root/'manifest.json'
            manifest.write_text('{"sources":[]}', encoding='utf-8')
            lib = PersonalLibrary(dict(base, knowledge_root=folder, source_roots=[], retrieval={'manifest':str(manifest)}))
            def map_item():
                return lib.dispatch({'action':'map.get'})['item']
            self.assertEqual(map_item()['domains'], [])
            topics = root/'01_我的思想体系'/'按话题读作品.md'
            topics.parent.mkdir()
            topics.write_text('## 写作\n### 怎样组织原话？\n', encoding='utf-8')
            self.assertEqual(map_item()['domains'][0]['questions'][0]['title'], '怎样组织原话？')
            self.assertEqual(map_item()['parts'], [])

    def test_correction_preserves_voice_and_raw_bytes(self):
        import hashlib
        base=yl_profile()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder);manifest=root/'清单.json';manifest.write_text('{"sources":[]}')
            src=root/'录音.md';raw='我就说，我就说。\n[环境噪音]\n只有不断去使用这套方法才会让我真的记住它。\n这次十别错了。\n'
            src.write_text(raw,encoding='utf8')
            lib=PersonalLibrary(dict(base,knowledge_root=folder,source_roots=[],retrieval={'manifest':str(manifest)}))
            req=dict(authorship='user_owned',source_id='fixture',title='口播',source_path=str(src),source_sha256=hashlib.sha256(src.read_bytes()).hexdigest(),corrections=[{'kind':'识别错误','line':4,'before':'十别','after':'识别'}])
            first=lib.register(req);self.assertEqual(lib.register(req),first)
            item=lib.get_work('fixture')
            self.assertNotIn('[环境噪音]',item['text'])
            self.assertIn('我就说，我就说。',item['text']);self.assertIn('这次识别错了。',item['text'])
            self.assertEqual(src.read_text('utf8'),raw)
            self.assertEqual(len(lib.verified_quotes(True)),1)

    def test_both_clients_share_sources_and_rejections(self):
        installed=yl_profile()
        with tempfile.TemporaryDirectory() as folder:
            root=Path(folder)
            source=root/'录音镜像.md'
            raw='# 录音\n\n## 本人\n\n为什么？为什么？我的系统可以反复用。\n\n## 旁人\n\n这是其他人的句子。\n'
            source.write_text(raw,encoding='utf-8')
            manifest=root/'manifest.json'
            manifest.write_text(json.dumps({'sources':[{'source_id':'work-1','title':'录音','path':str(source),'kind':'work','authorship':'user_owned','include_sections':['本人']}]},ensure_ascii=False),'utf8')
            config={'core_root':installed['core_root'],'knowledge_root':folder,'retrieval':{'manifest':str(manifest)}}
            left=PersonalLibrary(config);right=PersonalLibrary(config)
            def act(lib,action,**args):return lib.dispatch(dict(action=action,**args))
            self.assertNotIn('其他人',act(left,'works.get',source_id='work-1')['item']['text'])
            with self.assertRaises(ValueError):act(left,'quotes.add',source_id='work-1',text='这是其他人的句子。')
            result=act(left,'quotes.suggest',items=[{'source_id':'work-1','text':'我的系统可以反复用。','start_line':5,'topic':'复利','contexts':['长期生意']},{'source_id':'未审核','text':'我不属于该范围。'}])
            self.assertEqual(len(result['accepted']),1);self.assertEqual(len(result['withheld']),1)
            q=result['accepted'][0]
            self.assertEqual(right.verified_quotes(True)[0]['origin'],'source_extraction')
            self.assertEqual(act(right,'quotes.list',q='长期生意')['total'],1)
            act(right,'quotes.add',source_id='work-1',text='我的系统可以反复用。')
            self.assertEqual(left.verified_quotes(True)[0]['origin'],'hand_selected')
            act(left,'quotes.remove',id=q)
            self.assertEqual(right.verified_quotes(True),[])
            with self.assertRaises(ValueError):act(right,'quotes.add',source_id='work-1',text='我的系统可以反复用。')
            act(left,'quotes.add',source_id='work-1',text='我的系统可以反复用。',restore=True)
            original=act(right,'works.get',source_id='work-1')['item']
            body='为什么？为什么？这就是我的工作流。'
            act(left,'works.save',source_id='work-1',title='录音',expected_hash=original['hash'],text=body)
            with self.assertRaises(ValueError):act(right,'works.save',source_id='work-1',title='录音',expected_hash=original['hash'],text='旧客户端')
            corrected=act(right,'works.get',source_id='work-1')['item']
            self.assertEqual(corrected['text'],body)
            self.assertEqual(source.read_text('utf8'),raw)
            self.assertEqual(left.verified_quotes(True),[])
            self.assertEqual(act(left,'works.save',title='相同正文',text=body)['item']['source_id'],'work-1')
            act(left,'works.remove',source_id='work-1',expected_hash=corrected['hash'])
            self.assertEqual(act(right,'works.list')['total'],0)
            self.assertTrue(source.exists())
            new=act(left,'works.save',title='新作品',text=body)['item']
            self.assertEqual(act(right,'works.get',source_id=new['source_id'])['item']['text'],body)
            self.assertFalse((root/'05_知识原子').exists())


if __name__=='__main__':unittest.main()

