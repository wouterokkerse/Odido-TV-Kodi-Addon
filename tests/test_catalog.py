"""Regression coverage for the reference plugin's public OTT ID source."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
from urllib.error import URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin.video.odidotv'))
from resources.lib.catalog import load_channels, validate, SNAPSHOT
from resources.lib.storage import read_json, write_json
from resources.lib.api import Client


class CatalogTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.profile = self.directory.name
        self.feed = read_json(SNAPSHOT)

    def test_snapshot_preserves_reference_pairs_and_channel_order(self):
        rows = validate(self.feed)
        self.assertEqual(len(rows), 266)
        self.assertEqual([(r['ID'], r['physicalChannels'][0]['mediaID']) for r in rows[:4]],
                         [('141430714', '141430715'), ('147053128', '147053129'),
                          ('141430597', '141430598'), ('155053485', '155053486')])

    def test_media_is_not_assumed_to_equal_channel_plus_one(self):
        rtl8 = next(r for r in validate(self.feed) if r['name'] == 'RTL 8')
        self.assertEqual(rtl8['ID'], '141430473')
        self.assertEqual(rtl8['physicalChannels'][0]['mediaID'], '186566279')

    def test_refresh_uses_feed_then_reuses_valid_daily_cache(self):
        fetch = Mock(return_value=self.feed)
        rows = load_channels(self.profile, fetch=fetch)
        self.assertEqual(rows, load_channels(self.profile, fetch=fetch))
        fetch.assert_called_once_with()

    def test_offline_first_install_uses_bundled_mapping(self):
        self.assertEqual(load_channels(self.profile, fetch=Mock(side_effect=URLError('offline'))),
                         validate(self.feed))

    def test_invalid_refresh_retains_last_good_mapping(self):
        write_json(Path(self.profile)/'channel_catalog.json', {'updated': 0, 'channels': self.feed})
        self.assertEqual(load_channels(self.profile, fetch=lambda: {'not': 'a catalogue'}),
                         validate(self.feed))

    def test_mismatched_channel_key_is_rejected(self):
        with self.assertRaises(ValueError):
            validate({'1': {'id': '2', 'assetid': '3', 'name': 'Wrong pair'}})

    def test_live_guide_and_playback_use_exact_same_reference_pair(self):
        ok = lambda **fields: dict(result={'retCode': '000000000'}, **fields)
        transport = Mock(return_value=ok(csrfToken='synthetic'))
        client = Client(self.profile, transport=transport,
                        catalog_loader=lambda profile: validate(self.feed))
        client.login('synthetic-user', '0000')
        transport.reset_mock()
        transport.side_effect = [ok(), ok(channelPlaybills=[{'playbillLites': [
            {'ID': '700', 'channelID': '141430714', 'name': 'Fixture programme'}]}]),
            ok(playURL='https://example.test/fixture.mpd')]
        client.stream('channel', client.channels()[0]['id'])
        calls = transport.call_args_list
        self.assertEqual(calls[1].args[1]['queryChannel']['channelIDs'], ['141430714'])
        self.assertEqual(calls[2].args[0], 'PlayChannel')
        self.assertEqual(calls[2].args[1], {
            'businessType': 'CUTV', 'channelID': '141430714',
            'mediaID': '141430715', 'playbillID': '700',
            'checkLock': {'checkType': '0'}, 'isHTTPS': '1', 'isReturnProduct': '1'})
