"""Selective refresh requests preserve the other callback's saved payload."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin.video.odidotv'))
from resources.lib.api import OdidoError
from resources.lib.refresh import cached, complete, payload_path, pending, request
from resources.lib.storage import write_json


class RefreshTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.profile = self.directory.name
        self.manager = Mock()
        self.now = 1_800_000_000

    def save(self, kind):
        payload = {'version': 1, 'streams': []} if kind == 'channels' else {'version': 1, 'epg': {}}
        write_json(payload_path(self.profile, kind), {'payload': payload, 'updated': self.now - 300})

    def test_guide_only_requires_saved_channels_without_scheduling_on_failure(self):
        with self.assertRaisesRegex(OdidoError, 'BASELINE_REQUIRED'):
            request(self.profile, self.manager, mode='epg', now=self.now)
        self.manager.setSetting.assert_not_called()
        self.assertEqual(pending(self.profile, self.now), {})

    def test_channels_only_requires_saved_guide(self):
        with self.assertRaisesRegex(OdidoError, 'BASELINE_REQUIRED'):
            request(self.profile, self.manager, mode='channels', now=self.now)
        self.manager.setSetting.assert_not_called()

    def test_split_request_preserves_mode_and_wakes_silent_manager(self):
        self.save('channels')
        request(self.profile, self.manager, mode='epg', force=True, now=self.now)
        self.assertEqual(pending(self.profile, self.now)['mode'], 'epg')
        self.assertTrue(pending(self.profile, self.now)['force'])
        self.manager.setSetting.assert_called_once_with('last_refreshed', '0')

    def test_pending_request_cannot_be_replaced(self):
        request(self.profile, self.manager, now=self.now)
        original = pending(self.profile, self.now)
        with self.assertRaisesRegex(OdidoError, 'BUSY'):
            request(self.profile, self.manager, now=self.now + 10)
        self.assertEqual(pending(self.profile, self.now + 10), original)

    def test_failed_manager_schedule_removes_request(self):
        self.manager.setSetting.side_effect = RuntimeError('unavailable')
        with self.assertRaises(RuntimeError):
            request(self.profile, self.manager, now=self.now)
        self.assertEqual(pending(self.profile, self.now), {})

    def test_abandoned_request_expires_and_can_be_retried(self):
        request(self.profile, self.manager, now=self.now)
        request(self.profile, self.manager, now=self.now + 1801)
        self.assertEqual(self.manager.setSetting.call_count, 2)

    def test_late_callback_cannot_clear_new_request(self):
        request(self.profile, self.manager, now=self.now)
        old = pending(self.profile, self.now)
        request(self.profile, self.manager, now=self.now + 1801)
        current = pending(self.profile, self.now + 1801)
        complete(self.profile, old)
        self.assertEqual(pending(self.profile, self.now + 1801), current)

    def test_corrupt_saved_payload_does_not_allow_selective_refresh(self):
        write_json(payload_path(self.profile, 'epg'), {'payload': {'version': 1, 'epg': 'invalid'}})
        self.assertIsNone(cached(self.profile, 'epg'))
        with self.assertRaisesRegex(OdidoError, 'BASELINE_REQUIRED'):
            request(self.profile, self.manager, mode='channels', now=self.now)


if __name__ == '__main__':
    unittest.main()
