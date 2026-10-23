"""Background imports use Manager's silent scheduler, independently of UI/playback."""
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin.video.odidotv'))
from resources.lib.background import GuideRefresh, MANAGER
from resources.lib.storage import write_json


class GuideRefreshTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.profile = Path(self.directory.name)
        self.now, self.mono = 1_800_000_000, 0
        self.settings = {'iptv.enabled': 'true', 'iptv.auto_refresh': 'true'}
        self.addon, self.manager = Mock(), Mock()
        self.addon.getSetting.side_effect = lambda key: self.settings.get(key, '')
        self.enabled = Mock(return_value=True)
        self.get_addon = Mock(return_value=self.manager)
        self.scheduler = GuideRefresh(str(self.profile), self.addon, self.get_addon,
                                      self.enabled, lambda: self.now, lambda: self.mono)
        self.session({'logged_in': True, 'csrf_token': 'synthetic'})

    def session(self, value):
        write_json(str(self.profile / 'session.json'), value)

    def status(self, phase, age=0, error='', kind='epg'):
        write_json(str(self.profile / ('iptv_export_' + kind + '.json')),
                   {'phase': phase, 'updated': self.now - age, 'error': error})

    def advance(self, seconds):
        self.now += seconds
        self.mono += seconds
        self.scheduler.tick()

    def test_startup_requests_silent_import_after_grace_period(self):
        self.advance(59)
        self.manager.setSetting.assert_not_called()
        self.advance(1)
        self.get_addon.assert_called_once_with(MANAGER)
        # Manager's background service checks last_refreshed every 30 seconds.
        # No manual RunScript refresh, settings dialog or UI dependency.
        self.manager.setSetting.assert_called_once_with('last_refreshed', '0')
        self.addon.setSetting.assert_not_called()

    def test_successful_export_prevents_duplicate_import_until_hour_old(self):
        self.status('sent')
        self.advance(60)
        self.manager.setSetting.assert_not_called()
        self.advance(3540)
        self.manager.setSetting.assert_called_once()

    def test_failed_import_retries_only_after_fifteen_minutes(self):
        self.status('sent', error='NETWORK_ERROR')
        self.advance(60)
        # An actual EPG callback finishes/removes its scoped request, even on
        # failure; until then a queued import must not be overwritten.
        from resources.lib.refresh import complete, pending
        complete(str(self.profile), pending(str(self.profile), self.now))
        self.advance(899)
        self.assertEqual(self.manager.setSetting.call_count, 1)
        self.advance(1)
        self.assertEqual(self.manager.setSetting.call_count, 2)

    def test_reused_old_guide_does_not_count_as_new_fetch(self):
        write_json(str(self.profile / 'iptv_export_epg.json'),
                   {'phase': 'sent', 'updated': self.now, 'fetched': self.now - 7200,
                    'reused': True, 'error': ''})
        self.advance(60)
        self.manager.setSetting.assert_called_once()

    def test_disabled_integration_or_auto_refresh_does_not_request_import(self):
        for setting in ('iptv.enabled', 'iptv.auto_refresh'):
            with self.subTest(setting=setting):
                self.settings[setting] = 'false'
                self.advance(60)
                self.manager.setSetting.assert_not_called()
                self.settings[setting] = 'true'

    def test_missing_or_disabled_dependencies_do_not_request_import(self):
        for dependency in (MANAGER, 'pvr.iptvsimple'):
            with self.subTest(dependency=dependency):
                self.enabled.side_effect = lambda identifier: identifier != dependency
                self.advance(60)
                self.get_addon.assert_not_called()

    def test_saved_credentials_allow_refresh_after_session_loss(self):
        self.session({'credentials': {'username': 'synthetic', 'pin': '0012'}})
        self.advance(60)
        self.manager.setSetting.assert_called_once()

    def test_signed_out_or_missing_profile_does_not_request_import(self):
        self.session({'logged_in': False})
        self.advance(60)
        (self.profile / 'session.json').unlink()
        self.advance(60)
        self.manager.setSetting.assert_not_called()

    def test_active_manual_or_automatic_exports_are_not_interrupted(self):
        for kind in ('channels', 'epg'):
            with self.subTest(kind=kind):
                self.status('started', kind=kind)
                self.advance(60)
                self.manager.setSetting.assert_not_called()
                (self.profile / ('iptv_export_' + kind + '.json')).unlink()

    def test_abandoned_import_recovers_after_busy_timeout(self):
        self.status('started', age=1800)
        self.advance(60)
        self.manager.setSetting.assert_called_once()

    def test_future_export_timestamp_does_not_block_refresh_after_clock_change(self):
        self.status('sent', age=-3600)
        self.advance(60)
        self.manager.setSetting.assert_called_once()

    def test_shutdown_during_service_grace_period_makes_no_request(self):
        self.scheduler.tick()
        self.manager.setSetting.assert_not_called()


if __name__ == '__main__':
    unittest.main()
