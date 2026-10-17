"""Optional local Estuary copy: the native TV Previous button seeks to zero.

Stock application/skin files are never modified. All original assets and licence
files are copied from the Estuary already installed on the user's device.
"""
import os
import shutil
import tempfile
import xml.etree.ElementTree as ET

SKIN_ID = 'skin.estuary.odidotv'
SKIN_NAME = 'Estuary (TV buffer start)'
TV = 'VideoPlayer.Content(livetv)'
SEEK = 'PlayerControl(SeekPercentage(0))'
PREVIOUS = 'PlayerControl(Previous)'
MARKER = 'ODIDO-TV-MODIFICATIONS.txt'


def patch_osd(text):
    root = ET.fromstring(text)
    buttons = [item for item in root.iter('control') if item.get('id') == '600']
    if len(buttons) != 1:
        raise ValueError('SKIN_UNSUPPORTED_OSD')
    button = buttons[0]
    actions = button.findall('onclick')
    if len(actions) == 2 and any(item.text == SEEK and item.get('condition') == TV for item in actions):
        return text
    if len(actions) != 1 or (actions[0].text or '').strip() != PREVIOUS or actions[0].get('condition'):
        raise ValueError('SKIN_UNSUPPORTED_OSD')
    original = actions[0]
    index = list(button).index(original)
    button.remove(original)
    live = ET.Element('onclick', {'condition': TV})
    live.text = SEEK
    other = ET.Element('onclick', {'condition': '!' + TV})
    other.text = PREVIOUS
    button.insert(index, live)
    button.insert(index + 1, other)
    return ET.tostring(root, encoding='unicode')


def manifest(text):
    root = ET.fromstring(text)
    if root.get('id') != 'skin.estuary':
        raise ValueError('SKIN_UNSUPPORTED')
    root.set('id', SKIN_ID)
    root.set('name', SKIN_NAME)
    root.set('version', root.get('version', '1.0.0') + '.1')
    root.set('provider-name', root.get('provider-name', 'Kodi') + ' / Odido TV integration')
    return ET.tostring(root, encoding='unicode')


def _read(vfs, path):
    stream = vfs.File(path)
    try:
        return stream.read()
    finally:
        stream.close()


def _write(path, text):
    descriptor, temporary = tempfile.mkstemp(dir=os.path.dirname(path))
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as stream:
            stream.write(text)
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def install(vfs, source, addons, progress=lambda count: None, cancelled=lambda: False):
    source = source.rstrip('/\\') + '/'
    patched_manifest = manifest(_read(vfs, source + 'addon.xml'))
    patched_osd = patch_osd(_read(vfs, source + 'xml/VideoOSD.xml'))
    os.makedirs(addons, exist_ok=True)
    destination = os.path.join(addons, SKIN_ID)
    if os.path.exists(destination):
        existing = ET.parse(os.path.join(destination, 'addon.xml')).getroot()
        if existing.get('id') != SKIN_ID or not os.path.isfile(os.path.join(destination, MARKER)):
            raise ValueError('SKIN_DESTINATION_EXISTS')
        path = os.path.join(destination, 'xml', 'VideoOSD.xml')
        with open(path, encoding='utf-8') as stream:
            current = stream.read()
        _write(path, patch_osd(current))
        return destination
    staging = tempfile.mkdtemp(prefix='.odido-estuary-', dir=addons)
    count = 0
    try:
        def copy_tree(relative='', depth=0):
            nonlocal count
            if depth > 16 or count > 20000:
                raise ValueError('SKIN_COPY_LIMIT')
            if cancelled():
                raise ValueError('SKIN_COPY_CANCELLED')
            folders, files = vfs.listdir(source + relative)
            for name in folders + files:
                if name in ('.', '..') or '/' in name or '\\' in name:
                    raise ValueError('SKIN_INVALID_PATH')
            local = os.path.join(staging, *relative.strip('/').split('/'))
            os.makedirs(local, exist_ok=True)
            for name in files:
                if not relative and name == 'addon.xml':
                    continue  # Publish the manifest only after the copy completes.
                if cancelled():
                    raise ValueError('SKIN_COPY_CANCELLED')
                if not vfs.copy(source + relative + name, os.path.join(local, name)):
                    raise OSError('SKIN_COPY_FAILED')
                count += 1
                progress(count)
            for name in folders:
                copy_tree(relative + name + '/', depth + 1)
        copy_tree()
        _write(os.path.join(staging, 'xml', 'VideoOSD.xml'), patched_osd)
        _write(os.path.join(staging, MARKER),
               'Local copy of the installed Estuary skin. Original authors and licences retained.\n'
               'Modification: VideoOSD control 600 seeks to percentage 0 during native live TV.\n'
               'Other playback retains PlayerControl(Previous). No provider stream is modified.\n')
        _write(os.path.join(staging, 'addon.xml'), patched_manifest)
        os.rename(staging, destination)
        return destination
    finally:
        if os.path.isdir(staging):
            shutil.rmtree(staging)
