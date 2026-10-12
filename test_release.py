import hashlib,json,tempfile,unittest
from pathlib import Path
from tools.install import install

class InstallTests(unittest.TestCase):
    def test_preflight_install_upgrade_and_tamper(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);package=root/'package';package.mkdir();vault=root/'vault';vault.mkdir()
            (package/'manifest.json').write_text('{"id":"yl-knowledge-workbench"}','utf-8')
            (package/'main.js').write_text('v1','utf-8')
            def index():
                data={f.name:hashlib.sha256(f.read_bytes()).hexdigest() for f in package.iterdir() if f.name!='FILES.json'}
                (package/'FILES.json').write_text(json.dumps(data),'utf-8')
            index();self.assertEqual(install(package,vault,True)['status'],'dry-run')
            self.assertFalse((vault/'.obsidian').exists())
            out=install(package,vault);dest=Path(out['path']);(dest/'data.json').write_text('{"name":"mine"}','utf-8')
            self.assertEqual(install(package,vault)['status'],'already-installed')
            (package/'main.js').write_text('v2','utf-8');index()
            with self.assertRaises(ValueError):install(package,vault)
            result=install(package,vault,upgrade=True)
            self.assertEqual((Path(result['backup'])/'main.js').read_text(),'v1')
            self.assertEqual((dest/'data.json').read_text(),'{"name":"mine"}')
            (dest/'main.js').write_text('local change','utf-8')
            with self.assertRaises(ValueError):install(package,vault,upgrade=True)
            (package/'main.js').write_text('corrupt','utf-8')
            with self.assertRaises(ValueError):install(package,vault,upgrade=True)

if __name__=='__main__':unittest.main()
