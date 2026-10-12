import tempfile,unittest
from pathlib import Path
from unittest.mock import patch
from server import LocalServer,create_server
from knowledge import reading_text,topic_summary,Knowledge

class ReadingTests(unittest.TestCase):
    def test_duplicate_launch_never_initializes_app(self):
        first=LocalServer(('127.0.0.1',0),object)
        try:
            with patch('server.App') as app:
                with self.assertRaises(OSError):create_server('unused',first.server_address[1])
                app.assert_not_called()
        finally:first.server_close()

    def test_source_presentation_preserves_meaning(self):
        text='来源：视频号平台已发布版本的音频转写（翔哥 2026-09-22 指示：本地无可靠文稿时以平台版本为准）\n转写：faster-whisper medium (local_files_only) · beam_size=5 · language=zh\n我希望技术帮助我完成心愿。\n我做了一个 ASR 工作流。'
        result=reading_text(text)
        self.assertEqual(result,'来源：视频号平台已发布版本的音频转写\n我希望技术帮助我完成心愿。\n我做了一个 ASR 工作流。')
        self.assertIn('beam_size',text)
        decorated='> **来源：视频号文字**（用户指示：保留原文件）。\n> ⚠️ ASR 文本，含识别噪声，**引用前需人工校订**。'
        self.assertEqual(reading_text(decorated),'> **来源：视频号文字**。')

    def test_topic_numbers_come_from_one_publication(self):
        metrics=[{'publication_id':'a','views':'1000','follows':'50','completion_rate':'.8'}, {'publication_id':'b','views':'9000','follows':None,'completion_rate':'.25'}]
        result=topic_summary(metrics,[{'publication_id':'a','content_attributed_orders':'5'}])
        self.assertEqual(result['views'],'9000');self.assertEqual(result['completion_rate'],'.25')
        self.assertIsNone(result['follows']);self.assertEqual(result['sale'],'待补')

    def test_conversion_windows_are_not_summed_or_overwritten(self):
        metrics=[{'publication_id':'a','views':'9000'}]
        rows=[{'publication_id':'a','content_attributed_orders':'5'}, {'publication_id':'a','content_attributed_orders':'0'}]
        self.assertEqual(topic_summary(metrics,rows)['sale'],'有')
        self.assertEqual(topic_summary(metrics,rows[1:])['sale'],'无')
        self.assertEqual(topic_summary(metrics,[{'publication_id':'a','content_attributed_orders':''}])['sale'],'待补')

    def test_work_endpoint_does_not_accept_filesystem_paths(self):
        k=Knowledge.__new__(Knowledge);k.works=[]
        with self.assertRaises(KeyError):k.work('../../private.md')

if __name__=='__main__':unittest.main()
