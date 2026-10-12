"""Verify release bytes, reproducibility, isolated installation and local doc links."""
import hashlib,json,re,sys,tempfile,zipfile
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from package_plugin import HERE,package,payload
from tools.install import install,manifest

def verify():
    archive=package();first=archive.read_bytes();package()
    assert archive.read_bytes()==first,'Non-reproducible package'
    with tempfile.TemporaryDirectory() as tmp:
        base=Path(tmp)
        with zipfile.ZipFile(archive) as z:
            expected={'yl-knowledge-workbench/'+n for n in payload()}|{'yl-knowledge-workbench/FILES.json'}
            assert set(z.namelist())==expected,'Unexpected ZIP contents'
            z.extractall(base)
        extracted=base/'yl-knowledge-workbench';manifest(extracted)
        for name,source in payload().items():assert (extracted/name).read_bytes()==source.read_bytes(),name
        vault=base/'vault';vault.mkdir();assert install(extracted,vault,True)['status']=='dry-run'
        assert not (vault/'.obsidian').exists()
        assert install(extracted,vault)['status']=='installed'
        assert install(extracted,vault)['status']=='already-installed'
    docs=[HERE/'README.md',HERE/'CONTRIBUTING.md',*list((HERE/'docs').glob('*.md'))]
    for f in docs:
        for target in re.findall(r'\]\(([^)]+)\)',f.read_text('utf-8')):
            if '://' in target or target.startswith('#'):continue
            assert (f.parent/target.split('#')[0]).exists(),f'{f.name}: {target}'
    print(json.dumps({'status':'PASS','zip_files':len(payload())+1,'screenshots':len(list((HERE/'docs/images').glob('*.jpg'))),'sha256':hashlib.sha256(first).hexdigest()}))

if __name__=='__main__':verify()
