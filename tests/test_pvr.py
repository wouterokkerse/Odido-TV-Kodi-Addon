"""Kodi 21 instance configuration regression tests, using real XML files."""
from pathlib import Path
import sys
import tempfile
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'plugin.video.odidotv'))
from resources.lib.pvr import NAME, configure, read, values


class PVRTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.profile = Path(self.directory.name)
        self.playlist = str(self.profile/'manager/playlist.m3u8')
        self.guide = str(self.profile/'manager/epg.xml')

    def write(self, name, settings):
        root = ET.Element('settings', {'version': '2'})
        for key, value in settings.items():
            ET.SubElement(root, 'setting', {'id': key}).text = value
        path = self.profile/name
        path.write_bytes(ET.tostring(root))
        return path

    def configure(self):
        name, changed = configure(self.profile, self.playlist, self.guide)
        return self.profile/name, changed

    def test_configure_creates_enabled_native_instance_with_local_paths_and_catchup(self):
        path, changed = self.configure()
        self.assertEqual(path.name, 'instance-settings-2.xml')
        settings = values(read(path))
        self.assertTrue(changed)
        self.assertEqual(settings['kodi_addon_instance_name'], NAME)
        self.assertEqual(settings['kodi_addon_instance_enabled'], 'true')
        self.assertEqual((settings['m3uPathType'], settings['epgPathType']), ('0', '0'))
        self.assertEqual((settings['m3uPath'], settings['epgPath']), (self.playlist, self.guide))
        self.assertEqual(settings['catchupEnabled'], 'true')
        self.assertEqual(settings['epgTimeShift'], '0')
        self.assertFalse((self.profile/'settings.xml').exists())

    def test_unrelated_migrated_source_and_global_settings_are_preserved_byte_for_byte(self):
        first = self.write('instance-settings-1.xml', {'kodi_addon_instance_name': 'Migrated Add-on Config',
                            'm3uPathType': '1', 'm3uUrl': 'https://other.example/playlist'})
        global_settings = self.write('settings.xml', {'unrelated': 'keep'})
        original = first.read_bytes(), global_settings.read_bytes()
        self.configure()
        self.assertEqual((first.read_bytes(), global_settings.read_bytes()), original)

    def test_existing_manager_instance_is_repaired_and_original_backup_retained(self):
        first = self.write('instance-settings-1.xml', {'kodi_addon_instance_name': 'Migrated Add-on Config',
                            'm3uPath': self.playlist, 'epgPath': self.guide, 'unrelated': 'keep'})
        original = first.read_bytes()
        path, changed = self.configure()
        self.assertEqual(path, first)
        self.assertTrue(changed)
        self.assertEqual(values(read(path))['unrelated'], 'keep')
        self.assertEqual(Path(str(path)+'.odido.bak').read_bytes(), original)
        self.configure()
        self.assertEqual(Path(str(path)+'.odido.bak').read_bytes(), original)

    def test_repeated_setup_is_idempotent_and_does_not_create_duplicates(self):
        path, _ = self.configure()
        original = path.read_bytes()
        self.assertEqual(self.configure(), (path, False))
        self.assertEqual(path.read_bytes(), original)
        self.assertEqual(len(list(self.profile.glob('instance-settings-*.xml'))), 1)

    def test_unused_manager_local_path_does_not_replace_active_foreign_remote_source(self):
        first = self.write('instance-settings-1.xml', {'m3uPathType': '1', 'm3uUrl': 'https://other.example',
                            'm3uPath': self.playlist, 'epgPath': self.guide})
        original = first.read_bytes()
        path, _ = self.configure()
        self.assertNotEqual(path, first)
        self.assertEqual(first.read_bytes(), original)

    def test_existing_ids_and_malformed_configs_are_not_overwritten(self):
        first = self.profile/'instance-settings-2.xml'
        first.write_text('not XML')
        path, _ = self.configure()
        self.assertEqual(path.name, 'instance-settings-3.xml')
        self.assertEqual(first.read_text(), 'not XML')

    def test_default_flags_are_removed_when_setting_actual_path(self):
        path, _ = self.configure()
        root = read(path)
        root.find("setting[@id='m3uPath']").set('default', 'true')
        path.write_bytes(ET.tostring(root))
        self.assertTrue(self.configure()[1])
        self.assertNotIn('default', read(path).find("setting[@id='m3uPath']").attrib)

    def test_special_paths_match_translated_existing_manager_instance(self):
        first = self.write('instance-settings-1.xml', {'m3uPath': 'special://manager/playlist.m3u8',
                            'epgPath': 'special://manager/epg.xml'})
        def translate(value):
            return value.replace('special://manager/', str(self.profile/'manager')+'/')
        name, _ = configure(self.profile, self.playlist, self.guide, translate)
        self.assertEqual(name, first.name)

    def test_unmigrated_foreign_global_source_is_not_hidden_by_new_instance(self):
        original = self.write('settings.xml', {'m3uUrl': 'https://other.example/playlist'})
        raw = original.read_bytes()
        with self.assertRaisesRegex(ValueError, '^IPTV_PVR_MIGRATE_FIRST$'):
            self.configure()
        self.assertEqual(original.read_bytes(), raw)
        self.assertEqual(list(self.profile.glob('instance-settings-*.xml')), [])
