"""Patch the actual OSD action, retaining stock skin/assets and movie actions."""
from pathlib import Path
import shutil
import sys
import tempfile
import types
import unittest
import xml.etree.ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'plugin.video.odidotv'))
from resources.lib.tvskin import SKIN_ID, TV, SEEK, PREVIOUS, MARKER, install, patch_osd, manifest

OSD = '<window><controls><control type="radiobutton" id="600"><onclick>PlayerControl(Previous)</onclick><visible>Player.SeekEnabled</visible></control><control id="602"><onclick>PlayerControl(Play)</onclick></control></controls></window>'
MANIFEST = '<addon id="skin.estuary" name="Estuary" version="4.0.0" provider-name="Original authors"><requires><import addon="xbmc.gui" version="5.17.0"/></requires><extension point="xbmc.addon.metadata"><license>Original licence</license></extension></addon>'


class SkinTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.source = self.root/'stock'
        (self.source/'xml').mkdir(parents=True)
        (self.source/'media').mkdir()
        (self.source/'addon.xml').write_text(MANIFEST)
        (self.source/'xml/VideoOSD.xml').write_text(OSD)
        (self.source/'LICENSE').write_text('Original licence retained')
        (self.source/'media/Textures.xbt').write_bytes(b'\x00\xffSynthetic binary texture\x00')
        def listdir(path):
            children = list(Path(path).iterdir())
            return [item.name for item in children if item.is_dir()], [item.name for item in children if item.is_file()]
        def copy(source, destination):
            shutil.copyfile(source, destination)
            return True
        self.vfs = types.SimpleNamespace(File=lambda path: open(path, encoding='utf-8'), listdir=listdir, copy=copy)
        self.addons = self.root/'addons'

    def install(self, **kwargs):
        return Path(install(self.vfs, str(self.source), str(self.addons), **kwargs))

    def test_tv_button_seeks_zero_but_other_playback_keeps_previous(self):
        root = ET.fromstring(patch_osd(OSD))
        button = root.find(".//control[@id='600']")
        self.assertEqual([(item.get('condition'), item.text) for item in button.findall('onclick')],
                         [(TV, SEEK), ('!' + TV, PREVIOUS)])
        self.assertEqual(button.findtext('visible'), 'Player.SeekEnabled')
        self.assertEqual(root.findtext(".//control[@id='602']/onclick"), 'PlayerControl(Play)')

    def test_patch_is_idempotent(self):
        patched = patch_osd(OSD)
        self.assertEqual(patch_osd(patched), patched)

    def test_unsupported_button_fails_without_guessing_control(self):
        for xml in (OSD.replace('id="600"', 'id="999"'), OSD.replace(PREVIOUS, 'RunScript(other)')):
            with self.assertRaisesRegex(ValueError, 'SKIN_UNSUPPORTED_OSD'):
                patch_osd(xml)

    def test_manifest_is_separate_skin_with_original_authors_licence_and_dependencies(self):
        root = ET.fromstring(manifest(MANIFEST))
        self.assertEqual(root.get('id'), SKIN_ID)
        self.assertIn('Original authors', root.get('provider-name'))
        self.assertEqual(root.findtext('.//license'), 'Original licence')
        self.assertEqual(root.find('requires/import').get('addon'), 'xbmc.gui')
        with self.assertRaisesRegex(ValueError, 'SKIN_UNSUPPORTED'):
            manifest(MANIFEST.replace('skin.estuary', 'skin.other'))

    def test_install_copies_binary_assets_and_licences_without_modifying_stock_skin(self):
        before = {path.relative_to(self.source): path.read_bytes() for path in self.source.rglob('*') if path.is_file()}
        result = self.install()
        self.assertEqual(result.name, SKIN_ID)
        self.assertEqual((result/'media/Textures.xbt').read_bytes(), (self.source/'media/Textures.xbt').read_bytes())
        self.assertEqual((result/'LICENSE').read_text(), 'Original licence retained')
        self.assertTrue((result/MARKER).is_file())
        self.assertEqual({path.relative_to(self.source): path.read_bytes() for path in self.source.rglob('*') if path.is_file()}, before)
        self.assertEqual(list(self.addons.iterdir()), [result])

    def test_reinstall_preserves_existing_copy_and_does_not_duplicate(self):
        result = self.install()
        custom = result/'local-user-preference.txt'
        custom.write_text('keep')
        self.assertEqual(self.install(), result)
        self.assertEqual(custom.read_text(), 'keep')
        self.assertEqual(len(list(self.addons.iterdir())), 1)

    def test_foreign_destination_is_not_overwritten(self):
        destination = self.addons/SKIN_ID
        destination.mkdir(parents=True)
        (destination/'addon.xml').write_text('<addon id="foreign"/>')
        with self.assertRaisesRegex(ValueError, 'SKIN_DESTINATION_EXISTS'):
            self.install()
        self.assertEqual((destination/'addon.xml').read_text(), '<addon id="foreign"/>')

    def test_cancelled_copy_leaves_no_partial_skin(self):
        with self.assertRaisesRegex(ValueError, 'SKIN_COPY_CANCELLED'):
            self.install(cancelled=lambda: True)
        self.assertEqual(list(self.addons.iterdir()), [])

    def test_failed_copy_leaves_no_partial_skin(self):
        self.vfs.copy = lambda *args: False
        with self.assertRaisesRegex(OSError, 'SKIN_COPY_FAILED'):
            self.install()
        self.assertEqual(list(self.addons.iterdir()), [])
