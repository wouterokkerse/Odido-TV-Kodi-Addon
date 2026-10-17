"""Playback mode decisions must not request replay while a programme is live."""
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/'plugin.video.odidotv'))
from resources.lib.api import OdidoError
from resources.lib.playmode import target


class PlayModeTests(unittest.TestCase):
    def test_explicit_live_overrides_buffer_default(self):
        self.assertEqual(target({'kind': 'channel', 'id': '18', 'start': 'live'}, 'begin', 1000),
                         ('channel', '18', '', 'live'))

    def test_default_and_explicit_beginning(self):
        for params in ({'kind': 'channel', 'id': '18'}, {'kind': 'channel', 'id': '18', 'start': 'begin'}):
            self.assertEqual(target(params, 'begin', 1000), ('channel', '18', '', 'begin'))

    def test_existing_replay_links_without_timing_remain_compatible(self):
        self.assertEqual(target({'kind': 'program', 'id': '77', 'channel': '18'}, 'begin', 1000),
                         ('program', '77', '18', None))

    def test_end_boundary_uses_completed_replay(self):
        params = {'kind': 'program', 'id': '77', 'channel': '18', 'programme_start': '1000', 'programme_end': '2000'}
        self.assertEqual(target(params, 'live', 1000), ('channel', '18', '', 'begin'))
        self.assertEqual(target(params, 'live', 2000), ('program', '77', '18', None))

    def test_future_programme_is_not_opened_as_a_different_live_show(self):
        with self.assertRaisesRegex(OdidoError, '^PROGRAMME_NOT_STARTED$'):
            target({'kind': 'program', 'id': '77', 'channel': '18',
                    'programme_start': '2000', 'programme_end': '3000'}, 'live', 1000)

    def test_malformed_bounds_and_unknown_start_are_rejected(self):
        for bounds in ({'programme_start': 'bad', 'programme_end': '3000'}, {'programme_start': '2000'},
                       {'programme_start': '3000', 'programme_end': '2000'}):
            with self.assertRaisesRegex(OdidoError, '^INVALID_PROGRAMME_TIMES$'):
                target({'kind': 'program', 'id': '77', 'channel': '18', **bounds}, 'live', 1000)
        with self.assertRaisesRegex(OdidoError, '^INVALID_LIVE_START$'):
            target({'kind': 'channel', 'id': '18', 'start': 'invalid'}, 'live', 1000)
