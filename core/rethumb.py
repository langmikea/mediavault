import sqlite3
from pathlib import Path
from PIL import Image

DB = r'C:\AI\Platform\MediaVault\core\mediavault.sqlite'
c = sqlite3.connect(DB)
rows = c.execute("SELECT id, local_asset_path, thumbnail_path FROM artifacts WHERE domain='hunter_root'").fetchall()
ok = 0
for art_id, asset, thumb in rows:
    if not asset or not thumb:
        print(f'SKIP {art_id}: missing path')
        continue
    p = Path(asset)
    t = Path(thumb)
    if not p.exists():
        print(f'MISSING {art_id}: {asset}')
        continue
    try:
        img = Image.open(p).convert('RGB')
        img.thumbnail((400,400), Image.LANCZOS)
        t.parent.mkdir(parents=True, exist_ok=True)
        img.save(t, 'JPEG', quality=85)
        print(f'OK {art_id}')
        ok += 1
    except Exception as e:
        print(f'ERROR {art_id}: {e}')
c.close()
print(f'Done: {ok} thumbnails regenerated')
