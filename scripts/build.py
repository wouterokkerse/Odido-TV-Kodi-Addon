"""Validate and reproducibly package the installable addon (stdlib only)."""
import ast
import hashlib
from pathlib import Path
import re
import shutil
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ADDON = ROOT / 'plugin.video.odidotv'
manifest = ET.parse(ADDON / 'addon.xml').getroot()
assert manifest.attrib['id'] == ADDON.name
assert (ADDON / manifest.find("extension[@point='xbmc.python.pluginsource']").attrib['library']).is_file()
for path in ADDON.rglob('*.xml'):
    ET.parse(path)
for path in ADDON.rglob('*.py'):
    ast.parse(path.read_text(encoding='utf-8'), filename=str(path))
for asset in manifest.findall("extension[@point='xbmc.addon.metadata']/assets/*"):
    assert (ADDON / asset.text).is_file(), asset.text
strings = (ROOT / 'scripts/localize.py').read_text()
ids = set(re.findall(r'^\s*(30\d{3}):', strings, re.M))
used = set(re.findall(r"\b(30\d{3})\b", (ADDON / 'resources/lib/plugin.py').read_text()))
used.update(re.findall(r'\b(30\d{3})\b', (ADDON / 'resources/settings.xml').read_text()))
assert used <= ids, used - ids
for language in ('en_gb', 'nl_nl'):
    text = (ADDON / ('resources/language/resource.language.%s/strings.po' % language)).read_text()
    assert set(re.findall(r'msgctxt "#(\d+)"', text)) == ids
shutil.copyfile(ROOT / 'LICENSE', ADDON / 'LICENSE')
shutil.copyfile(ROOT / 'README.md', ADDON / 'README.md')
shutil.copyfile(ROOT / 'SOURCES.md', ADDON / 'SOURCES.md')
output = ROOT / 'dist'
output.mkdir(exist_ok=True)
name = '%s-%s.zip' % (manifest.attrib['id'], manifest.attrib['version'])
target = output / name
with zipfile.ZipFile(target, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(ADDON.rglob('*')):
        if not path.is_file() or '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        info = zipfile.ZipInfo(str(path.relative_to(ROOT)), date_time=(2026, 10, 17, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        archive.writestr(info, path.read_bytes())
with zipfile.ZipFile(target) as archive:
    assert archive.testzip() is None
    assert all(name.startswith(ADDON.name + '/') for name in archive.namelist())
digest = hashlib.sha256(target.read_bytes()).hexdigest()
(output / (name + '.sha256')).write_text(digest + '  ' + name + '\n')
print('Validated and built: %s (%d bytes)' % (target, target.stat().st_size))
print('SHA-256: ' + digest)
