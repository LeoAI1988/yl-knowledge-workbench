"""Build a code-only plugin ZIP by explicit allowlist; never copy vault data."""
from pathlib import Path
import hashlib,io,json,zipfile
HERE=Path(__file__).resolve().parent
BACKEND=('server.py','knowledge.py','markdown_vault.py','astra.py')
DIST=('index.html','main.js','main.css')
PLUGIN=('manifest.json','main.js','styles.css')

def payload():
    files={name:HERE/'plugin'/name for name in PLUGIN}
    files.update({'backend/'+name:HERE/name for name in BACKEND})
    files.update({'backend/dist/'+name:HERE/'dist'/name for name in DIST})
    files['README.md']=HERE/'plugin/README.md'
    files['requirements.txt']=HERE/'plugin/requirements.txt'
    files['LICENSE']=HERE/'LICENSE'
    files['install.py']=HERE/'tools/install.py'
    files['THIRD_PARTY_NOTICES.txt']=HERE/'THIRD_PARTY_NOTICES.txt'
    return files

def notices():
    sections=[]
    for package in sorted((HERE/'node_modules/.pnpm').glob('*/node_modules/*')):
        packages=list(package.iterdir()) if package.name.startswith('@') and package.is_dir() else [package]
        for p in packages:
            if not (p/'package.json').is_file():continue
            meta=json.loads((p/'package.json').read_text('utf-8'))
            licenses=[f for f in p.iterdir() if f.is_file() and f.name.lower().startswith(('license','licence','copying'))]
            for f in licenses:sections.append(f"## {meta.get('name')} {meta.get('version')}\n\n"+f.read_text('utf-8',errors='replace'))
    return '\n\n'.join(dict.fromkeys(sections))

def package():
    dest=HERE/'releases';dest.mkdir(exist_ok=True)
    version=json.loads((HERE/'plugin/manifest.json').read_text('utf-8'))['version']
    target=dest/f'yl-knowledge-workbench-{version}.zip'
    files={name:path.read_bytes() for name,path in payload().items()}
    hashes={name:hashlib.sha256(data).hexdigest() for name,data in sorted(files.items())}
    files['FILES.json']=json.dumps(hashes,indent=2,sort_keys=True).encode()
    buffer=io.BytesIO()
    with zipfile.ZipFile(buffer,'w',zipfile.ZIP_DEFLATED) as z:
        for name,data in sorted(files.items()):
            info=zipfile.ZipInfo('yl-knowledge-workbench/'+name,(2026,1,1,0,0,0))
            info.compress_type=zipfile.ZIP_DEFLATED;info.create_system=3;info.external_attr=0o100644<<16
            z.writestr(info,data)
    archive=buffer.getvalue()
    if target.exists() and target.read_bytes()!=archive:raise ValueError('Version already built with different bytes; increment the version.')
    target.write_bytes(archive)
    digest=hashlib.sha256(archive).hexdigest()
    target.with_suffix('.zip.sha256').write_text(digest+'  '+target.name+'\n','utf-8')
    print(json.dumps({'package':str(target),'files':len(files),'bytes':len(archive),'sha256':digest},ensure_ascii=False))
    return target

if __name__=='__main__':package()
