"""Configure a Kodi 21 IPTV Simple instance, preserving other IPTV sources."""
import os
import re
import shutil
import tempfile
import xml.etree.ElementTree as ET

NAME = 'Odido TV (IPTV Manager)'
INSTANCE = re.compile(r'^instance-settings-([1-9][0-9]*)\.xml$')


def read(path):
    try:
        with open(path, 'rb') as stream:
            raw = stream.read(1024 * 1024 + 1)
        if len(raw) > 1024 * 1024:
            return None
        root = ET.fromstring(raw)
        return root if root.tag == 'settings' else None
    except (OSError, ET.ParseError):
        return None


def values(root):
    return {item.get('id'): item.text or '' for item in root.findall('setting')}


def configure(profile, playlist, guide, translate=lambda value: value):
    """Return (instance basename, changed) after setting the Manager file paths.

    Kodi discovers these filenames through CAddonInfo::GetKnownInstanceIds.
    The global settings.xml is only a migration source on Kodi 21.
    """
    os.makedirs(profile, exist_ok=True)
    playlist, guide = translate(playlist), translate(guide)
    expected = {'m3uPathType': '0', 'm3uPath': playlist, 'm3uUrl': '',
                'epgPathType': '0', 'epgPath': guide, 'epgUrl': '',
                'epgTimeShift': '0', 'catchupEnabled': 'true',
                'catchupDays': '7', 'allChannelsCatchupMode': '1',
                'catchupOnlyOnFinishedProgrammes': 'false',
                'kodi_addon_instance_name': NAME, 'kodi_addon_instance_enabled': 'true'}

    def same(value, target):
        return bool(value) and os.path.normcase(os.path.normpath(translate(value))) == os.path.normcase(os.path.normpath(target))

    root, target = None, None
    has_instances = False
    used = {1}  # Reserve Kodi's implicit first instance even if not saved yet.
    for filename in sorted(os.listdir(profile)):
        match = INSTANCE.fullmatch(filename)
        if not match:
            continue
        has_instances = True
        used.add(int(match[1]))
        path = os.path.join(profile, filename)
        if os.path.islink(path):
            continue
        candidate = read(path)
        if candidate is None:
            continue
        current = values(candidate)
        # An unused local path must not make an active remote provider ours.
        foreign_url = (current.get('m3uPathType', '1') == '1' and bool(current.get('m3uUrl'))) or (
            current.get('epgPathType', '1') == '1' and bool(current.get('epgUrl')))
        manager_paths = same(current.get('m3uPath', ''), playlist) and same(current.get('epgPath', ''), guide)
        if not foreign_url and (manager_paths or current.get('kodi_addon_instance_name') == NAME):
            target, root = path, candidate
            break
    creating = root is None
    if creating:
        # Adding the first physical instance would hide Kodi's implicit instance
        # 1. Do not hide an unrelated legacy source awaiting native migration.
        if not has_instances:
            legacy = read(os.path.join(profile, 'settings.xml'))
            if legacy is not None:
                current = values(legacy)
                foreign = bool(current.get('m3uUrl') or current.get('epgUrl')) or (
                    current.get('m3uPath') and not same(current['m3uPath'], playlist)) or (
                    current.get('epgPath') and not same(current['epgPath'], guide))
                if foreign:
                    raise ValueError('IPTV_PVR_MIGRATE_FIRST')
        identifier = 2
        while identifier in used:
            identifier += 1
        target = os.path.join(profile, 'instance-settings-%d.xml' % identifier)
        root = ET.Element('settings', {'version': '2'})
    changed = creating
    for key, value in expected.items():
        item = root.find("setting[@id='%s']" % key)
        if item is None:
            item = ET.SubElement(root, 'setting', {'id': key})
            changed = True
        if (item.text or '') != value or 'default' in item.attrib:
            item.text = value
            item.attrib.pop('default', None)
            changed = True
    if not changed:
        return os.path.basename(target), False
    if not creating and not os.path.exists(target + '.odido.bak'):
        shutil.copyfile(target, target + '.odido.bak')
        os.chmod(target + '.odido.bak', 0o600)
    descriptor, temporary = tempfile.mkstemp(dir=profile, prefix='.odido-pvr-')
    reserved_target = False
    try:
        with os.fdopen(descriptor, 'wb') as stream:
            stream.write(ET.tostring(root, encoding='utf-8', xml_declaration=True))
        if creating:
            # Reserve the name without overwriting a concurrently created source.
            reserved = os.open(target, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
            os.close(reserved)
            reserved_target = True
        os.replace(temporary, target)
        reserved_target = False
    finally:
        if reserved_target:
            os.unlink(target)
        if os.path.exists(temporary):
            os.unlink(temporary)
    return os.path.basename(target), True
