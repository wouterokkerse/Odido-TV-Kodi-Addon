"""Synthetic VSP fixtures; these are not captured production Odido responses."""
import http.cookiejar
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock
from urllib.error import HTTPError, URLError

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin.video.odidotv'))
from resources.lib.api import Client, OdidoError, AuthError, playback, media_id, record, normalize_device_name
from resources.lib.storage import SavedLists


def ok(**fields):
    return dict(result={'retCode': '000000000'}, **fields)


def channel():
    return {'ID': '18', 'name': 'Synthetic Channel', 'physicalChannels': [{'mediaID': '42'}]}


def program(identifier='77'):
    return {'ID': identifier, 'name': 'Synthetic Programme', 'startTime': 1000, 'endTime': 2000}


class ClientTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.transport = Mock(return_value=ok())
        self.catalog = Mock(return_value=[channel()])
        self.client = Client(self.directory.name, self.transport, catalog_loader=self.catalog)

    def signed_in(self):
        self.transport.return_value = ok(csrfToken='synthetic-csrf')
        self.client.login('synthetic-user', '0012')
        self.transport.reset_mock()
        self.transport.return_value = ok()

    def test_login_payload_preserves_leading_zero_pin(self):
        self.signed_in()
        self.transport.return_value = ok(csrfToken='new')
        self.client.login('synthetic-user', '0012')
        method, payload, params = self.transport.call_args.args
        self.assertEqual(method, 'Authenticate')
        self.assertEqual(payload['authenticateBasic']['clientPasswd'], '0012')
        self.assertEqual(payload['authenticateBasic']['userID'], 'synthetic-user')
        self.assertEqual(payload['authenticateDevice']['CADeviceInfos'][0]['CADeviceType'], '7')

    def test_login_requests_default_readable_device_name(self):
        self.signed_in()
        self.transport.return_value = ok(csrfToken='new')
        self.client.login('user', '0012')
        self.assertEqual(self.transport.call_args.args[1]['authenticateDevice']['deviceName'], 'Kodi Odido TV')

    def test_custom_name_survives_failed_login_without_new_identity(self):
        self.signed_in()
        device = self.client.state['device_id']
        self.transport.return_value = {'result': {'retCode': '157022007'}}
        renamed = Client(self.directory.name, self.transport, device_name='Kodi Living Room')
        with self.assertRaisesRegex(OdidoError, 'DEVICE_LIMIT'):
            renamed.login('user', '0012')
        payload = self.transport.call_args.args[1]['authenticateDevice']
        self.assertEqual(payload['deviceName'], 'Kodi Living Room')
        self.assertEqual(payload['deviceModel'], '3103_PCClient')
        self.assertEqual(payload['physicalDeviceID'], device)
        restarted = Client(self.directory.name)
        self.assertEqual(restarted.device_name, 'Kodi Living Room')
        self.assertEqual(restarted.state['device_id'], device)

    def test_legacy_state_migrates_without_rotating_device_id(self):
        self.signed_in()
        from resources.lib.storage import read_json, write_json
        state = read_json(self.client.state_path)
        state.pop('device_name', None)
        write_json(self.client.state_path, state)
        migrated = Client(self.directory.name, self.transport)
        self.assertEqual(migrated.device_name, 'Kodi Odido TV')
        self.assertEqual(migrated.state['device_id'], state['device_id'])

    def test_successful_credentials_saved_with_private_permissions(self):
        self.signed_in()
        again = Client(self.directory.name, self.transport)
        self.assertEqual(again.state['credentials'], {'username': 'synthetic-user', 'pin': '0012'})
        self.assertEqual(Path(self.client.state_path).stat().st_mode & 0o777, 0o600)
        self.assertEqual(Path(self.client.cookie_path).stat().st_mode & 0o777, 0o600)

    def test_missing_cookies_reauthenticates_with_saved_login_and_same_device(self):
        self.signed_in()
        device = self.client.state['device_id']
        Path(self.client.cookie_path).unlink()
        self.transport.return_value = ok(csrfToken='renewed')
        again = Client(self.directory.name, self.transport)
        self.assertFalse(again.logged_in)
        again.require_session()
        payload = self.transport.call_args.args[1]
        self.assertEqual(payload['authenticateBasic']['clientPasswd'], '0012')
        self.assertEqual(payload['authenticateDevice']['physicalDeviceID'], device)
        self.assertTrue(Client(self.directory.name).logged_in)

    def test_failed_first_login_does_not_save_credentials(self):
        self.transport.return_value = {'result': {'retCode': '123456'}}
        with self.assertRaises(OdidoError):
            self.client.login('wrong', 'bad')
        self.assertNotIn('credentials', Client(self.directory.name).state)

    def test_signed_out_profile_cannot_automatically_log_in(self):
        self.signed_in()
        background = Client(self.directory.name, self.transport)
        self.client.logout()
        self.assertNotIn('credentials', Client(self.directory.name).state)
        with self.assertRaisesRegex(AuthError, 'LOGIN_REQUIRED'):
            Client(self.directory.name, self.transport).require_session()
        with self.assertRaisesRegex(AuthError, 'SESSION_CHANGED'):
            background.login('synthetic-user', '0012')
        self.transport.assert_not_called()

    def test_device_id_and_session_survive_restart(self):
        self.signed_in()
        again = Client(self.directory.name)
        self.assertEqual(again.state['device_id'], self.client.state['device_id'])
        self.assertTrue(again.logged_in)
        self.assertEqual(again.state['csrf_token'], 'synthetic-csrf')

    def test_logout_clears_csrf_and_session_but_keeps_device(self):
        self.signed_in()
        device = self.client.state['device_id']
        self.client.logout()
        self.assertFalse(self.client.logged_in)
        self.assertEqual(self.client.state['csrf_token'], '')
        self.assertEqual(self.client.state['device_id'], device)

    def test_late_background_save_does_not_restore_signed_out_session(self):
        self.signed_in()
        background = Client(self.directory.name)
        self.client.logout()
        with self.assertRaisesRegex(AuthError, 'SESSION_CHANGED'):
            background._save()
        self.assertFalse(Client(self.directory.name).logged_in)

    def test_login_failure_clears_partial_state(self):
        self.signed_in()
        self.transport.return_value = ok()
        with self.assertRaisesRegex(OdidoError, 'NO_CSRF_TOKEN'):
            self.client.login('user', 'bad')
        self.assertFalse(self.client.logged_in)

    def test_device_limit_does_not_reuse_someone_elses_device(self):
        device = self.client.state['device_id']
        self.transport.return_value = {'result': {'retCode': '157022007'},
                                       'devices': [{'physicalDeviceID': 'another-device'}]}
        with self.assertRaisesRegex(OdidoError, '^DEVICE_LIMIT$'):
            self.client.login('user', '0012')
        self.assertEqual(self.client.state['device_id'], device)
        self.assertEqual(self.transport.call_count, 1)

    def test_error_messages_and_bad_codes_not_exposed(self):
        self.transport.return_value = {'result': {'retCode': 'https://private', 'retMsg': 'password'}}
        with self.assertRaisesRegex(OdidoError, '^API_UNKNOWN$'):
            self.client.request('Test')

    def test_heartbeat_provider_rejection_expires_session(self):
        self.signed_in()
        self.client.state.pop('credentials')  # Legacy session without saved login.
        self.transport.return_value = {'result': {'retCode': '123456'}}
        with self.assertRaisesRegex(AuthError, 'SESSION_REJECTED'):
            self.client.heartbeat()
        self.assertFalse(self.client.logged_in)

    def test_expired_heartbeat_renews_once_and_preserves_device(self):
        for rejection in (AuthError('HTTP_401'), {'result': {'retCode': '123456'}}):
            with self.subTest(rejection=rejection):
                self.signed_in()
                device = self.client.state['device_id']
                self.transport.side_effect = [rejection, ok(csrfToken='renewed'), ok()]
                self.client.heartbeat()
                self.assertEqual([c.args[0] for c in self.transport.call_args_list],
                                 ['OnLineHeartbeat', 'Authenticate', 'OnLineHeartbeat'])
                self.assertTrue(self.client.logged_in)
                self.assertEqual(self.client.state['device_id'], device)
                self.transport.side_effect = None

    def test_rejected_renewed_session_stops_without_retry_loop(self):
        self.signed_in()
        self.transport.side_effect = [AuthError('HTTP_401'), ok(csrfToken='new'), AuthError('HTTP_401')]
        with self.assertRaisesRegex(AuthError, 'HTTP_401'):
            self.client.heartbeat()
        self.assertEqual(self.transport.call_count, 3)
        self.assertFalse(self.client.logged_in)

    def test_failed_renewal_keeps_saved_login_for_network_retry(self):
        self.signed_in()
        self.transport.side_effect = [AuthError('HTTP_401'), OdidoError('NETWORK_ERROR')]
        with self.assertRaisesRegex(OdidoError, 'NETWORK_ERROR'):
            self.client.heartbeat()
        self.assertEqual(Client(self.directory.name).state['credentials']['pin'], '0012')

    def test_sign_out_during_heartbeat_never_reauthenticates(self):
        self.signed_in()
        background = Client(self.directory.name, self.transport)
        def sign_out(*args):
            self.client.logout()
            return ok(csrfToken='late-response')
        self.transport.side_effect = sign_out
        with self.assertRaisesRegex(AuthError, 'SESSION_CHANGED'):
            background.heartbeat()
        self.assertEqual(self.transport.call_count, 1)
        restarted = Client(self.directory.name)
        self.assertFalse(restarted.logged_in)
        self.assertNotIn('credentials', restarted.state)

    def test_network_failure_keeps_session_for_retry(self):
        self.signed_in()
        self.transport.side_effect = OdidoError('NETWORK_ERROR')
        with self.assertRaises(OdidoError):
            self.client.heartbeat()
        self.assertTrue(self.client.logged_in)

    def test_channels_use_reference_ott_catalogue_without_queryallchannel(self):
        self.signed_in()
        self.assertEqual(self.client.channels()[0]['id'], '18')
        self.catalog.assert_called_once_with(self.directory.name)
        self.transport.assert_not_called()

    def test_unavailable_channel_catalogue_fails_clearly(self):
        self.signed_in()
        self.catalog.side_effect = ValueError('private detail')
        with self.assertRaisesRegex(OdidoError, '^CHANNEL_CATALOG_UNAVAILABLE$'):
            self.client.channels()

    def test_live_stream_uses_provider_media_identifier(self):
        self.signed_in()
        self.transport.side_effect = [ok(),
                                      ok(channelPlaybills=[{'channelID': '18', 'playbillLites': [program()]}]),
                                      ok(playURL='https://cdn.example/a.mpd?sig=a%2Bb&limit=1')]
        result = self.client.stream('channel', '18')
        self.assertEqual(result['url'], 'https://cdn.example/a.mpd?sig=a%2Bb&limit=1')
        self.assertEqual(self.transport.call_args.args[0], 'PlayChannel')
        payload = self.transport.call_args.args[1]
        self.assertEqual(payload['mediaID'], '42')
        self.assertEqual(payload['businessType'], 'CUTV')
        self.assertEqual(payload['playbillID'], '77')
        self.assertEqual(payload['checkLock'], {'checkType': '0'})
        guide_call = self.transport.call_args_list[1]
        self.assertEqual(guide_call.args[0], 'QueryPlaybillListStcProps')
        query = guide_call.args[1]['queryPlaybill']
        self.assertEqual(query['startTime'], query['endTime'])
        self.assertEqual(query['count'], '1')
        self.assertEqual(guide_call.args[1]['queryChannel']['channelIDs'], ['18'])

    def test_live_without_current_programme_does_not_send_invalid_play_request(self):
        self.signed_in()
        self.transport.side_effect = [ok(), ok(channelPlaybills=[])]
        with self.assertRaisesRegex(OdidoError, '^NO_CURRENT_PROGRAMME$'):
            self.client.stream('channel', '18')
        self.assertEqual(self.transport.call_count, 2)
        self.assertTrue(self.client.logged_in)

    def test_playback_rejection_identifies_stage_without_provider_message(self):
        self.signed_in()
        self.transport.side_effect = [ok(),
                                      ok(channelPlaybills=[{'channelID': '18', 'playbillLites': [program()]}]),
                                      {'result': {'retCode': '146020013', 'retMsg': 'private provider message'}}]
        with self.assertRaisesRegex(OdidoError, '^API_146020013_PLAYCHANNEL$'):
            self.client.stream('channel', '18')
        self.assertEqual(self.transport.call_count, 3)
        self.assertTrue(self.client.logged_in)

    def test_guide_rejection_does_not_reach_playchannel(self):
        self.signed_in()
        self.transport.side_effect = [ok(), {'result': {'retCode': '146020013'}}]
        with self.assertRaisesRegex(OdidoError, '^API_146020013_GUIDE$'):
            self.client.stream('channel', '18')
        self.assertEqual(self.transport.call_count, 2)

    def test_replay_request_keeps_channel_and_playbill(self):
        self.signed_in()
        self.transport.side_effect = [ok(), ok(playbillDetail={'channelID': '18'}),
                                      ok(playURL='https://cdn.example/replay.mpd')]
        self.client.stream('program', '77')
        payload = self.transport.call_args.args[1]
        self.assertEqual(payload['channelID'], '18')
        self.assertEqual(payload['playbillID'], '77')
        self.assertEqual(payload['businessType'], 'CUTV')

    def test_login_required_before_any_playback_call(self):
        with self.assertRaises(AuthError):
            self.client.stream('channel', '18')
        self.transport.assert_not_called()

    def test_now_fetches_one_page_without_pagination_loop(self):
        self.signed_in()
        self.transport.return_value = ok(channelPlaybills=[{'channelID': '18', 'playbillLites': [program()]}])
        rows = self.client.now(['18'])
        self.assertEqual(rows[0]['channel'], '18')
        self.assertEqual(self.transport.call_count, 1)

    def test_live_listing_bounds_266_channel_requests(self):
        self.signed_in()
        def answer(method, payload, params):
            channels = payload['queryChannel']['channelIDs']
            self.assertLessEqual(len(channels), 20)
            self.assertEqual(payload['queryPlaybill']['count'], '1')
            return ok(channelPlaybills=[{'playbillLites': [dict(program(c), channelID=c)]} for c in channels])
        self.transport.side_effect = answer
        channels = [str(n) for n in range(266)]
        rows, errors = self.client.live_programmes(channels)
        self.assertEqual([row['channel'] for row in rows], channels)
        self.assertEqual(errors, [])
        self.assertEqual(self.transport.call_count, 14)

    def test_rejected_live_group_falls_back_to_single_channels(self):
        self.signed_in()
        self.transport.side_effect = [
            {'result': {'retCode': '146020013'}},
            ok(channelPlaybills=[{'playbillLites': [program('1')]}]),
            ok(channelPlaybills=[{'playbillLites': [program('2')]}])]
        rows, errors = self.client.live_programmes(['18', '19'])
        self.assertEqual([row['channel'] for row in rows], ['18', '19'])
        self.assertEqual(errors, [])
        self.assertEqual([call.args[1]['queryChannel']['channelIDs'] for call in self.transport.call_args_list],
                         [['18', '19'], ['18'], ['19']])

    def test_unavailable_channel_does_not_discard_other_live_programmes(self):
        self.signed_in()
        rejected = {'result': {'retCode': '146020013'}}
        self.transport.side_effect = [rejected, rejected,
            ok(channelPlaybills=[{'playbillLites': [program('2')]}])]
        rows, errors = self.client.live_programmes(['18', '19'])
        self.assertEqual([row['channel'] for row in rows], ['19'])
        self.assertEqual(errors, ['API_146020013_GUIDE'])

    def test_live_network_failure_does_not_trigger_individual_retry_storm(self):
        self.signed_in()
        self.transport.side_effect = OdidoError('NETWORK_ERROR')
        self.assertEqual(self.client.live_programmes(['18', '19']), ([], ['NETWORK_ERROR']))
        self.assertEqual(self.transport.call_count, 1)

    def test_live_auth_failure_stops_menu_requests(self):
        self.signed_in()
        self.transport.side_effect = AuthError('HTTP_401')
        with self.assertRaisesRegex(AuthError, '^HTTP_401$'):
            self.client.live_programmes(['18', '19'])
        self.assertEqual(self.transport.call_count, 1)

    def test_empty_live_listing_does_not_request_guide(self):
        self.signed_in()
        self.assertEqual(self.client.live_programmes([]), ([], []))
        self.transport.assert_not_called()

    def test_guide_pagination_preserves_all_programmes(self):
        self.signed_in()
        self.transport.side_effect = [
            ok(channelPlaybills=[{'channelID': '18', 'playbillLites': [program('1'), program('2')]}]),
            ok(channelPlaybills=[{'channelID': '18', 'playbillLites': [program('3')]}])]
        rows = self.client.epg(['18'], 0, 5000, count=2)
        self.assertEqual([r['id'] for r in rows], ['1', '2', '3'])
        self.assertEqual(self.transport.call_args.args[1]['queryPlaybill']['offset'], '2')

    def test_replay_day_matches_reference_amsterdam_request(self):
        self.signed_in()
        self.transport.return_value = ok(channelPlaybills=[{'playbillLites': [program()]}])
        self.assertEqual(self.client.day('18', '20260606')[0]['id'], '77')
        method, payload, params = self.transport.call_args.args
        self.assertEqual(method, 'QueryPlaybillListStcProps')
        self.assertEqual(payload['queryPlaybill'], {
            'count': '300', 'offset': '0', 'type': '0', 'isFillProgram': '1',
            'startTime': 1780696800000, 'endTime': 1780783199000})
        self.assertEqual(payload['queryChannel']['channelIDs'], ['18'])
        self.assertEqual(params['DID'], self.client.state['device_id'])
        self.assertEqual(self.transport.call_count, 1)

    def test_guide_nullable_metadata_does_not_raise_typeerror(self):
        self.signed_in()
        self.transport.return_value = ok(channelPlaybills=[{'playbillLites': [dict(
            program(), picture={'posters': None}, introduce=None)]}])
        row = self.client.day('18', '20260606')[0]
        self.assertEqual(row['image'], '')
        self.assertEqual(row['plot'], '')
        self.assertEqual(row['channel'], '18')

    def test_null_timestamps_and_picture_are_normalized(self):
        row = record(dict(program(), startTime=None, endTime=None, picture=None), 'program', '18')
        self.assertEqual((row['start'], row['end'], row['duration']), (0, 0, 0))
        self.assertEqual(row['image'], '')

    def test_repeated_page_fails_instead_of_silent_truncation(self):
        self.signed_in()
        self.transport.return_value = ok(channelPlaybills=[{'channelID': '18', 'playbillLites': [program()]}])
        with self.assertRaisesRegex(OdidoError, 'PAGINATION_STALLED'):
            self.client.epg(['18'], 0, 5000, count=1)

    def test_cookie_and_csrf_scoping(self):
        self.signed_in()
        cookie = http.cookiejar.Cookie(0, 'session', 'synthetic', None, False,
                                      'tv.odido.nl', False, False, '/', True, True,
                                      None, True, None, None, {}, False)
        self.client.jar.set_cookie(cookie)
        first = self.client.media_headers('https://tv.odido.nl/VSP/V3/ExternalDRMLicense', True, 'custom')
        self.assertIn('Cookie', first)
        self.assertEqual(first['X_CSRFToken'], 'synthetic-csrf')
        self.assertEqual(first['AcquireLicense.CustomData'], 'custom')
        other = self.client.media_headers('https://cdn.example/a.mpd')
        self.assertNotIn('Cookie', other)
        self.assertNotIn('X_CSRFToken', other)
        self.assertNotIn('AcquireLicense.CustomData', other)
        external_license = self.client.media_headers('https://license.example/wv', True)
        self.assertNotIn('X_CSRFToken', external_license)

    def test_http_error_sanitized_and_unauthorized_expires_session(self):
        self.signed_in()
        self.client.transport = self.client._http
        self.client.opener.open = Mock(side_effect=HTTPError('https://private', 401, 'secret', {}, None))
        with self.assertRaisesRegex(AuthError, '^HTTP_401$'):
            self.client.heartbeat()
        self.assertFalse(self.client.logged_in)

    def test_transport_failure_sanitized(self):
        self.client.opener.open = Mock(side_effect=URLError('private-token'))
        with self.assertRaisesRegex(OdidoError, '^NETWORK_ERROR$'):
            self.client._http('Test', {}, {})

    def test_saved_lists_deduplicate_and_survive_logout(self):
        lists = SavedLists(self.directory.name)
        item = record(program(), 'program', '18')
        lists.update('later', item)
        lists.update('later', item)
        self.client.logout()
        self.assertEqual(lists.items('later'), [item])
        lists.update('later', item, remove=True)
        self.assertEqual(lists.items('later'), [])


class ResponseTests(unittest.TestCase):
    def test_device_name_normalized_and_bounded(self):
        self.assertEqual(normalize_device_name('  Kodi\r\n Living\tRoom  '), 'Kodi Living Room')
        self.assertEqual(normalize_device_name('  '), 'Kodi Odido TV')
        self.assertEqual(len(normalize_device_name('x' * 100)), 64)

    def test_clear_dash_supported(self):
        self.assertEqual(playback(ok(playURL='https://cdn.example/clear.mpd'))['license'], '')

    def test_widevine_custom_data_extracted_without_changing_signature(self):
        value = ok(playURL='https://cdn.example/a.mpd?sig=a%2Bb', authorizeResult={
            'triggers': [{'licenseURL': 'https://tv.odido.nl/VSP/V3/ExternalDRMLicense', 'customData': 'opaque'}]})
        result = playback(value)
        self.assertEqual(result['custom_data'], 'opaque')
        self.assertEqual(result['url'], value['playURL'])

    def test_invalid_url_schemes_rejected(self):
        with self.assertRaisesRegex(OdidoError, 'NO_HTTPS_MANIFEST'):
            playback(ok(playURL='plugin://example'))
        with self.assertRaisesRegex(OdidoError, 'INVALID_LICENSE_URL'):
            playback(ok(playURL='https://cdn.example/a.mpd', authorizeResult={'triggers': [{'licenseURL': 'http://unsafe'}]}))

    def test_no_media_does_not_invent_identifier(self):
        with self.assertRaisesRegex(OdidoError, 'NO_MEDIA_ID'):
            media_id({'ID': '18'})

    def test_missing_content_id_rejected(self):
        with self.assertRaisesRegex(OdidoError, 'MISSING_CONTENT_ID'):
            record({}, 'program')


if __name__ == '__main__':
    unittest.main()
