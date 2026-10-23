"""Kodi repository metadata, package integrity and release safety."""
import hashlib
import importlib.util
import io
from pathlib import Path
import shutil
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('build_repository', ROOT / 'scripts/build_repository.py')
builder = importlib.util.module_from_spec(spec)
spec.loader.exec_module(builder)


class RepositoryTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name) / 'source'
        self.output = Path(self.directory.name) / 'feed'
        self.root.mkdir()
        for identifier in ('plugin.video.odidotv', 'repository.odidotv'):
            directory = self.root / identifier
            directory.mkdir()
            for name in ('addon.xml', 'icon.png'):
                shutil.copyfile(ROOT / identifier / name, directory / name)
        shutil.copyfile(ROOT / 'LICENSE', self.root / 'LICENSE')
        (self.root / 'dist').mkdir()
        self.package()

    def package(self, release=None, extra=b''):
        manifest = self.root / 'plugin.video.odidotv/addon.xml'
        tree = ET.parse(manifest)
        if release:
            tree.getroot().set('version', release)
            tree.write(manifest, encoding='utf-8', xml_declaration=True)
        self.release = tree.getroot().get('version')
        data = builder.archive_files({'plugin.video.odidotv/addon.xml': manifest.read_bytes(),
                                      'plugin.video.odidotv/default.py': extra})
        (self.root / 'dist' / ('plugin.video.odidotv-' + self.release + '.zip')).write_bytes(data)

    def build(self):
        builder.build(self.output, self.root)

    def snapshot(self):
        return {str(p.relative_to(self.output)): p.read_bytes()
                for p in self.output.rglob('*') if p.is_file()}

    def test_feed_checksum_and_kodi_package_paths(self):
        self.build()
        xml = (self.output / 'addons.xml').read_bytes()
        self.assertEqual((self.output / 'addons.xml.md5').read_text().strip(), hashlib.md5(xml).hexdigest())
        addons = ET.fromstring(xml)
        self.assertEqual({a.get('id') for a in addons}, {'plugin.video.odidotv', 'repository.odidotv'})
        for addon in addons:
            identifier, release = addon.get('id'), addon.get('version')
            path = self.output / identifier / (identifier + '-' + release + '.zip')
            data = path.read_bytes()
            self.assertEqual(Path(str(path) + '.md5').read_text().strip(), hashlib.md5(data).hexdigest())
            self.assertEqual(Path(str(path) + '.sha256').read_text().split()[0], hashlib.sha256(data).hexdigest())
            with zipfile.ZipFile(io.BytesIO(data)) as archive:
                self.assertIsNone(archive.testzip())
                manifest = ET.fromstring(archive.read(identifier + '/addon.xml'))
                self.assertEqual(manifest.get('version'), release)
            self.assertTrue((self.output / identifier / 'icon.png').is_file())

    def test_repository_installer_points_to_published_feed(self):
        self.build()
        with zipfile.ZipFile(self.output / 'repository.odidotv/repository.odidotv-1.0.0.zip') as archive:
            root = ET.fromstring(archive.read('repository.odidotv/addon.xml'))
            extension = root.find("extension[@point='xbmc.addon.repository']")
            self.assertEqual(extension.find('dir/info').text, builder.BASE_URL + 'addons.xml')
            self.assertEqual(extension.find('dir/checksum').text, builder.BASE_URL + 'addons.xml.md5')
            self.assertEqual(extension.find('dir/datadir').attrib['zip'], 'true')
            self.assertIn('repository.odidotv/LICENSE', archive.namelist())

    def test_repeated_build_has_identical_bytes(self):
        self.build()
        before = self.snapshot()
        self.build()
        self.assertEqual(before, self.snapshot())

    def test_update_preserves_old_packages(self):
        self.package('0.2.7')
        self.build()
        old = (self.output / 'plugin.video.odidotv/plugin.video.odidotv-0.2.7.zip').read_bytes()
        self.package('0.2.8', b'updated')
        self.build()
        self.assertEqual((self.output / 'plugin.video.odidotv/plugin.video.odidotv-0.2.7.zip').read_bytes(), old)
        plugin = ET.parse(self.output / 'addons.xml').getroot().find("addon[@id='plugin.video.odidotv']")
        self.assertEqual(plugin.get('version'), '0.2.8')

    def test_same_version_changed_bytes_rejected_before_any_write(self):
        self.build()
        before = self.snapshot()
        self.package(extra=b'changed without version bump')
        with self.assertRaisesRegex(ValueError, 'version bump'):
            self.build()
        self.assertEqual(before, self.snapshot())

    def test_version_downgrade_rejected_before_any_write(self):
        self.package('0.2.8')
        self.build()
        before = self.snapshot()
        self.package('0.2.7')
        with self.assertRaisesRegex(ValueError, 'downgrade'):
            self.build()
        self.assertEqual(before, self.snapshot())

    def test_manifest_and_zip_version_must_match(self):
        path = self.root / 'dist' / ('plugin.video.odidotv-' + self.release + '.zip')
        self.package('0.2.99')
        shutil.copyfile(path, self.root / 'dist/plugin.video.odidotv-0.2.99.zip')
        with self.assertRaisesRegex(AssertionError, 'Stale package'):
            self.build()
        self.assertFalse((self.output / 'addons.xml').exists())


if __name__ == '__main__':
    unittest.main()
