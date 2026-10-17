"""IPTV Manager v1 payload, callback, caching and replay contract tests."""
import datetime as dt
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
from urllib.parse import parse_qs, urlparse
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugin.video.odidotv'))
from resources.lib.api import AuthError, OdidoError
from resources.lib.iptv import Exporter, selection, send
from resources.lib.storage import read_json, write_json

NOW = dt.datetime(2026, 6, 6, 12, tzinfo=dt.timezone.utc).timestamp()


def channels():
    return [{'ID': '18', 'name': 'NPO & één', 'channelno': '1',
             'logo': 'https://example.test/logo.png', 'replay': True},
            {'ID': '19', 'name': 'Channel 2', 'channelno': '2', 'replay': False}]


def programme(channel='18', start=None):
    start = int(NOW * 1000) - 1800000 if start is None else start
    return {'id': '700' + channel, 'channel': channel, 'title': 'Nieuws — België',
            'plot': 'A & B < C', 'start': start, 'end': start + 3600000, 'image': ''}


class ExportTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.client = Mock()
        self.client.profile = self.directory.name
        self.client.channel_rows.return_value = channels()
        self.client.epg.return_value = [programme()]

    def exporter(self, selected=None, clock=lambda: NOW):
        return Exporter(self.client, selected, clock=clock)

    def test_channel_payload_contains_stable_ids_numbers_logos_and_plugin_links(self):
        payload = self.exporter().channels()
        self.assertEqual(payload['version'], 1)
        first, second = payload['streams']
        self.assertEqual((first['id'], first['preset'], first['logo']),
                         ('odido.18', 1, 'https://example.test/logo.png'))
        self.assertEqual(second['logo'], 'icon.png')
        query = parse_qs(urlparse(first['stream']).query)
        self.assertEqual(query['kind'], ['channel'])
        self.assertEqual(query['id'], ['18'])
        self.assertEqual(urlparse(first['stream']).netloc, 'plugin.video.odidotv')
        self.assertEqual(first['group'], ['Odido TV'])
        self.client.stream.assert_not_called()
        self.assertNotIn('csrf', json.dumps(payload))

    def test_selected_channels_apply_to_streams_and_epg(self):
        exporter = self.exporter({'18'})
        self.assertEqual(len(exporter.channels()['streams']), 1)
        self.assertEqual(set(exporter.epg(1)['epg']), {'odido.18'})
        for call in self.client.epg.call_args_list:
            self.assertEqual(call.args[0], ['18'])

    def test_explicit_empty_selection_does_not_export_or_fetch_channels(self):
        exporter = self.exporter(set())
        self.assertEqual(exporter.channels()['streams'], [])
        self.assertEqual(exporter.epg(1)['epg'], {})
        self.client.epg.assert_not_called()

    def test_logged_out_export_cannot_reuse_cache_or_start_interactive_login(self):
        self.client.require_session.side_effect = AuthError('LOGIN_REQUIRED')
        with self.assertRaisesRegex(AuthError, 'LOGIN_REQUIRED'):
            self.exporter()
        self.client.channel_rows.assert_not_called()

    def test_epg_uses_timezone_aware_dates_and_replay_links_with_same_channel_id(self):
        payload = self.exporter().epg(1)
        row = payload['epg']['odido.18'][0]
        self.assertEqual(dt.datetime.fromisoformat(row['start']).utcoffset(), dt.timedelta(0))
        query = parse_qs(urlparse(row['stream']).query)
        self.assertEqual(query['kind'], ['program'])
        self.assertEqual(query['id'], ['70018'])
        self.assertEqual(query['channel'], ['18'])
        self.assertEqual(row['description'], 'A & B < C')
        self.assertEqual(len(payload['epg']['odido.18']), 1)  # Cross-day duplicates removed.

    def test_future_links_become_live_without_refresh_but_finished_non_replay_has_no_link(self):
        from resources.lib.playmode import target
        self.client.epg.return_value = [programme(start=int((NOW + 3600) * 1000)),
                                       programme('19', start=int((NOW - 7200) * 1000))]
        payload = self.exporter().epg(1)
        params = {key: value[0] for key, value in parse_qs(urlparse(payload['epg']['odido.18'][0]['stream']).query).items()}
        with self.assertRaisesRegex(OdidoError, 'PROGRAMME_NOT_STARTED'):
            target(params, 'live', NOW * 1000)
        self.assertEqual(target(params, 'live', (NOW + 4000) * 1000), ('channel', '18', '', 'begin'))
        self.assertNotIn('stream', payload['epg']['odido.19'][0])

    def test_current_programme_link_uses_live_buffer_then_replay_when_finished(self):
        from resources.lib.playmode import target
        payload = self.exporter().epg(1)
        params = {key: value[0] for key, value in parse_qs(urlparse(payload['epg']['odido.18'][0]['stream']).query).items()}
        self.assertEqual(target(params, 'live', NOW * 1000), ('channel', '18', '', 'begin'))
        self.assertEqual(target(params, 'live', (NOW + 3600) * 1000), ('program', '70018', '18', None))

    def test_current_non_replay_channel_can_open_live_buffer_but_not_finished_replay(self):
        from resources.lib.playmode import target
        self.client.epg.return_value = [programme('19')]
        payload = self.exporter().epg(1)
        params = {key: value[0] for key, value in parse_qs(urlparse(payload['epg']['odido.19'][0]['stream']).query).items()}
        self.assertEqual(target(params, 'live', NOW * 1000), ('channel', '19', '', 'begin'))
        with self.assertRaisesRegex(OdidoError, 'REPLAY_UNAVAILABLE'):
            target(params, 'live', (NOW + 3600) * 1000)

    def test_bad_timestamps_do_not_break_entire_epg(self):
        self.client.epg.return_value = [programme(), dict(programme(), start=None), dict(programme(), end=0)]
        self.assertEqual(len(self.exporter().epg(1)['epg']['odido.18']), 1)

    def test_cached_schedule_avoids_repeat_requests_and_refreshes_today(self):
        self.exporter().epg(3)
        self.assertEqual(self.client.epg.call_count, 4)  # Today, tomorrow and two past days.
        self.client.epg.reset_mock()
        self.exporter().epg(3)
        self.client.epg.assert_not_called()
        self.exporter(clock=lambda: NOW + 1800).epg(3)
        self.assertEqual(self.client.epg.call_count, 1)  # Only today's 15-minute cache expired.

    def test_group_rejection_falls_back_and_preserves_stale_failed_channel(self):
        stale = {'19': {'updated': 0, 'rows': [programme('19')]}}
        write_json(Path(self.directory.name)/'iptv_epg/20260606.json', stale)
        def query(identifiers, start, end, count):
            if len(identifiers) > 1 or identifiers == ['19']:
                raise OdidoError('API_123_GUIDE')
            return [programme()]
        self.client.epg.side_effect = query
        exporter = self.exporter()
        result = exporter.epg(1)['epg']
        self.assertTrue(result['odido.18'])
        self.assertTrue(result['odido.19'])
        self.assertIn('API_123_GUIDE', exporter.errors)
        cached = read_json(Path(self.directory.name)/'iptv_epg/20260606.json')
        self.assertEqual(cached['19']['updated'], 0)

    def test_network_failure_stops_further_requests_and_uses_cached_days(self):
        write_json(Path(self.directory.name)/'iptv_epg/20260606.json',
                   {'18': {'updated': 0, 'rows': [programme()]}})
        self.client.epg.side_effect = OdidoError('NETWORK_ERROR')
        exporter = self.exporter()
        self.assertTrue(exporter.epg(7)['epg']['odido.18'])
        self.assertEqual(self.client.epg.call_count, 1)
        self.assertEqual(exporter.errors, ['NETWORK_ERROR'])

    def test_cancelled_import_stops_before_guide_requests(self):
        exporter = Exporter(self.client, cancelled=lambda: True)
        with self.assertRaisesRegex(OdidoError, 'IPTV_CANCELLED'):
            exporter.epg(7)
        self.client.epg.assert_not_called()


class CallbackTests(unittest.TestCase):
    def test_callback_connects_before_slow_production_and_uses_sendall(self):
        events = []
        context = Mock()
        connection = context.__enter__ = Mock(return_value=Mock())
        context.__exit__ = Mock()
        def connect(address, timeout):
            events.append('connect')
            self.assertEqual(address, ('127.0.0.1', 23456))
            return context
        def producer():
            events.append('produce')
            return {'version': 1, 'streams': [{'name': 'é' * 10000}]}
        send('23456', 'channels', producer, Mock(), connect=connect)
        self.assertEqual(events, ['connect', 'produce'])
        raw = connection.return_value.sendall.call_args.args[0]
        self.assertTrue(raw.isascii())
        self.assertEqual(json.loads(raw)['streams'][0]['name'], 'é' * 10000)

    def test_invalid_callback_ports_do_not_connect_or_fetch(self):
        for port in (None, 'invalid', '80', '65536', '-1'):
            connect, producer = Mock(), Mock()
            with self.assertRaises(OdidoError):
                send(port, 'epg', producer, Mock(), connect=connect)
            connect.assert_not_called()
            producer.assert_not_called()

    def test_failed_background_export_sends_empty_versioned_response_and_reports_safely(self):
        context = Mock()
        context.__enter__ = Mock(return_value=Mock())
        context.__exit__ = Mock()
        report = Mock()
        send(23456, 'epg', Mock(side_effect=AuthError('LOGIN_REQUIRED')), report,
             connect=Mock(return_value=context))
        self.assertEqual(json.loads(context.__enter__.return_value.sendall.call_args.args[0]),
                         {'version': 1, 'epg': {}})
        self.assertEqual(str(report.call_args.args[0]), 'LOGIN_REQUIRED')
        context.__exit__.assert_called_once()

    def test_selection_distinguishes_all_none_and_invalid(self):
        self.assertIsNone(selection(''))
        self.assertEqual(selection('[]'), set())
        self.assertEqual(selection('["18"]'), {'18'})
        with self.assertRaises(OdidoError):
            selection('{"private": "value"}')

    def test_settings_publish_manager_discovery_endpoints_with_opt_in(self):
        root = ET.parse(ROOT/'plugin.video.odidotv/resources/settings.xml').getroot()
        settings = {item.get('id'): item for item in root.iter('setting') if item.get('id')}
        self.assertEqual(settings['iptv.enabled'].get('default'), 'false')
        for name, action in (('channels', 'iptv_channels'), ('epg', 'iptv_epg')):
            uri = settings['iptv.' + name + '_uri'].get('default')
            self.assertEqual(urlparse(uri).netloc, 'plugin.video.odidotv')
            self.assertEqual(parse_qs(urlparse(uri).query)['action'], [action])
        addon = ET.parse(ROOT/'plugin.video.odidotv/addon.xml').getroot()
        dependency = addon.find("requires/import[@addon='service.iptv.manager']")
        self.assertEqual(dependency.get('optional'), 'true')
