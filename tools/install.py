"""Install an extracted, verified release; preserve data.json and user state."""
import argparse, hashlib, json, shutil
from datetime import datetime
from pathlib import Path, PurePosixPath

PLUGIN_ID='yl-knowledge-workbench'
def manifest(folder):
    value=json.loads((folder/'FILES.json').read_text('utf-8'))
    if not isinstance(value,dict) or not value:raise ValueError('Invalid file manifest')
    for name,digest in value.items():
        p=PurePosixPath(name)
        if p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name:raise ValueError('Unsafe manifest path')
        f=folder.joinpath(*p.parts)
        if not f.resolve().is_relative_to(folder.resolve()) or f.is_symlink():raise ValueError('Linked package file')
        if not f.is_file() or hashlib.sha256(f.read_bytes()).hexdigest()!=digest:raise ValueError('Missing or modified file: '+name)
    meta=json.loads((folder/'manifest.json').read_text('utf-8'))
    if meta.get('id')!=PLUGIN_ID:raise ValueError('Unexpected plugin ID')
    return value

def install(package,vault,dry_run=False,upgrade=False):
    package=Path(package).resolve();vault=Path(vault).resolve()
    if not vault.is_dir():raise ValueError('Vault directory does not exist')
    incoming=manifest(package)
    dest=vault/'.obsidian/plugins'/PLUGIN_ID
    if not dest.resolve().is_relative_to(vault):raise ValueError('Plugin target escapes vault')
    old={}
    if dest.exists():
        old=manifest(dest)  # Fail closed on unknown or modified core.
        known=set(old)|{'FILES.json','data.json'}
        actual={p.relative_to(dest).as_posix() for p in dest.rglob('*') if p.is_file()}
        if actual-known:raise ValueError('Unmanaged files found; keep a backup and resolve manually')
        if old==incoming:return {'status':'already-installed','path':str(dest)}
        if not upgrade:raise ValueError('Existing version differs; use --upgrade after review')
    if dry_run:return {'status':'dry-run','files':len(incoming),'path':str(dest)}
    backup=None
    if old:
        backup=vault/'.obsidian/plugin-backups'/f'{PLUGIN_ID}-{datetime.now():%Y%m%d-%H%M%S-%f}'
        backup.parent.mkdir(parents=True,exist_ok=True);shutil.copytree(dest,backup)
    dest.mkdir(parents=True,exist_ok=True)
    for name in sorted(incoming):
        target=dest/name;target.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(package/name,target)
    for name in old.keys()-incoming.keys():
        (dest/name).unlink()  # Only a previously verified managed file.
    shutil.copy2(package/'FILES.json',dest/'FILES.json')
    manifest(dest)
    return {'status':'installed','path':str(dest),'backup':str(backup) if backup else None}

if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--package',type=Path,default=Path(__file__).resolve().parent)
    p.add_argument('--vault',type=Path,required=True)
    p.add_argument('--dry-run',action='store_true');p.add_argument('--upgrade',action='store_true')
    a=p.parse_args()
    try:print(json.dumps(install(a.package,a.vault,a.dry_run,a.upgrade),ensure_ascii=False))
    except (ValueError,OSError) as e:p.exit(1,str(e)+'\n')
