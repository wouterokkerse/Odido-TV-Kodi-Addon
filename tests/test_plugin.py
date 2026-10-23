"""Kodi API doubles for navigation, playback and heartbeat ownership."""
import importlib.util
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'plugin.video.odidotv'))


def channel():
    return {'kind': 'channel', 'id': '18', 'channel': '', 'title': 'Channel', 'plot': '', 'image': '', 'start': 0, 'end': 0, 'duration': 0}


class PluginTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.items = []
        self.kodi, self.gui, self.kplugin = Mock(), Mock(), Mock()
        self.gui.ListItem.side_effect = self.new_item
        addon = Mock()
        addon.getSetting.return_value = 'Kodi Living Room'
        addon.getAddonInfo.side_effect = lambda key: self.directory.name if key == 'profile' else '0.1.0'
        addon.getLocalizedString.side_effect = str
        pvr_addon, manager_addon = Mock(), Mock()
        pvr_addon.getAddonInfo.return_value = str(Path(self.directory.name)/'pvr')
        manager_addon.getAddonInfo.return_value = str(Path(self.directory.name)/'manager')
        self.pvr_addon, self.manager_addon = pvr_addon, manager_addon
        self.helper = Mock()
        modules = {'xbmc': self.kodi, 'xbmcgui': self.gui, 'xbmcplugin': self.kplugin,
                   'xbmcaddon': types.SimpleNamespace(Addon=lambda addon_id=None: {
                       'pvr.iptvsimple': pvr_addon, 'service.iptv.manager': manager_addon}.get(addon_id, addon)),
                   'xbmcvfs': types.SimpleNamespace(translatePath=lambda p: p), 'inputstreamhelper': self.helper}
        self.patcher = patch.dict(sys.modules, modules)
        self.patcher.start()
        self.addCleanup(self.patcher.stop)
        sys.modules.pop('resources.lib.plugin', None)
        from resources.lib.plugin import Plugin
        self.Plugin = Plugin
        self.registration = patch('resources.lib.plugin.register_playback', return_value={
            'url': 'http://127.0.0.1:12345/secret/session/manifest.mpd',
            'license': 'http://127.0.0.1:12345/secret/session/license'})
        self.register = self.registration.start()
        self.addCleanup(self.registration.stop)

    def new_item(self, **kwargs):
        item = Mock()
        item.kwargs = kwargs
        self.items.append(item)
        return item

    def plugin(self, query):
        plugin = self.Plugin(['plugin://plugin.video.odidotv/', '1', query])
        plugin.client = Mock()
        plugin.client.logged_in = True
        return plugin

    def test_live_is_playable_not_folder(self):
        plugin = self.plugin('?action=live')
        plugin.client.channels.return_value = [channel()]
        plugin.client.live_programmes.return_value = ([], [])
        plugin.dispatch()
        self.assertFalse(self.kplugin.addDirectoryItem.call_args.kwargs['isFolder'])
        self.items[0].setProperty.assert_any_call('IsPlayable', 'true')

    def test_login_pin_masked_and_preserved(self):
        plugin = self.plugin('?action=login')
        plugin.dialog.input.side_effect = ['customer', '0012']
        plugin.dispatch()
        plugin.client.login.assert_called_once_with('customer', '0012')
        self.assertEqual(plugin.dialog.input.call_args.kwargs['option'], self.gui.ALPHANUM_HIDE_INPUT)

    def test_guide_failure_reports_code_and_keeps_channels_playable(self):
        from resources.lib.api import OdidoError
        plugin = self.plugin('?action=live')
        plugin.client.channels.return_value = [channel()]
        plugin.client.live_programmes.side_effect = OdidoError('API_146020013_GUIDE')
        plugin.dispatch()
        self.assertIn('API_146020013_GUIDE', self.gui.Dialog.return_value.notification.call_args.args[1])
        self.gui.Window.return_value.setProperty.assert_called_with(
            'plugin.video.odidotv.last_guide_error', 'API_146020013_GUIDE')
        self.kplugin.addDirectoryItem.assert_called_once()

    def test_live_partial_information_still_displays_successful_programmes(self):
        plugin = self.plugin('?action=live')
        plugin.client.channels.return_value = [channel()]
        plugin.client.live_programmes.return_value = ([{
            'channel': '18', 'title': 'Current programme', 'plot': 'Programme synopsis'}], ['API_123_GUIDE'])
        plugin.dispatch()
        self.assertEqual(self.items[0].kwargs['label'], 'Channel — Current programme')
        self.items[0].getVideoInfoTag.return_value.setPlot.assert_called_with('Programme synopsis')
        self.kplugin.addDirectoryItem.assert_called_once()

    def test_live_successful_fallback_clears_warning(self):
        plugin = self.plugin('?action=live')
        plugin.client.channels.return_value = [channel()]
        plugin.client.live_programmes.return_value = ([{
            'channel': '18', 'title': 'Current programme', 'plot': ''}], [])
        plugin.dispatch()
        plugin.dialog.notification.assert_not_called()
        self.gui.Window.return_value.clearProperty.assert_called_with('plugin.video.odidotv.last_guide_error')

    def test_iptv_callback_is_background_only_and_uses_existing_session(self):
        from resources.lib import plugin as module
        plugin = self.plugin('?action=iptv_channels&port=23456')
        plugin.addon.getSetting.side_effect = lambda key: {'iptv.enabled': 'true', 'iptv.selected': '["18"]'}.get(key, '')
        plugin.client.channel_rows.return_value = [{'ID': '18', 'name': 'Channel', 'channelno': '1'}]
        with patch.object(module, 'send_iptv') as sender:
            plugin.dispatch()
            self.assertEqual(sender.call_args.args[:2], ('23456', 'channels'))
            payload = sender.call_args.args[2]()
        self.assertEqual(payload['streams'][0]['id'], 'odido.18')
        plugin.dialog.input.assert_not_called()
        plugin.dialog.ok.assert_not_called()
        self.kplugin.endOfDirectory.assert_not_called()
        self.kplugin.setResolvedUrl.assert_not_called()

    def test_disabled_iptv_export_does_not_query_provider(self):
        from resources.lib import plugin as module
        plugin = self.plugin('?action=iptv_epg&port=23456')
        plugin.addon.getSetting.return_value = 'false'
        with patch.object(module, 'send_iptv') as sender:
            plugin.dispatch()
            self.assertEqual(sender.call_args.args[2](), {'version': 1, 'epg': {}})
        plugin.client.channel_rows.assert_not_called()
        plugin.dialog.input.assert_not_called()

    def test_epg_callback_renews_login_without_opening_dialogs(self):
        from resources.lib import plugin as module
        plugin = self.plugin('?action=iptv_epg&port=23456')
        plugin.addon.getSetting.side_effect = lambda key: {'iptv.enabled': 'true', 'iptv.days': '7'}.get(key, '')
        with patch.object(module, 'send_iptv') as sender, patch.object(module, 'Exporter') as exporter:
            exporter.return_value.epg.return_value = {'version': 1, 'epg': {}}
            exporter.return_value.errors = []
            plugin.dispatch()
            sender.call_args.args[2]()
        plugin.client.heartbeat.assert_called_once()
        plugin.dialog.input.assert_not_called()
        plugin.dialog.ok.assert_not_called()

    def test_epg_preflight_network_failure_still_exports_cached_guide(self):
        from resources.lib import plugin as module
        from resources.lib.api import OdidoError
        plugin = self.plugin('?action=iptv_epg&port=23456')
        plugin.addon.getSetting.side_effect = lambda key: {'iptv.enabled': 'true', 'iptv.days': '7'}.get(key, '')
        plugin.client.heartbeat.side_effect = OdidoError('NETWORK_ERROR')
        with patch.object(module, 'send_iptv') as sender, patch.object(module, 'Exporter') as exporter:
            exporter.return_value.epg.return_value = {'version': 1, 'epg': {'odido.18': []}}
            exporter.return_value.errors = ['NETWORK_ERROR']
            plugin.dispatch()
            result = sender.call_args.args[2]()
        self.assertIn('odido.18', result['epg'])
        plugin.dialog.ok.assert_not_called()

    def test_iptv_refresh_persists_discovery_before_running_manager(self):
        from unittest.mock import call
        plugin = self.plugin('?action=iptv_refresh')
        self.kodi.getCondVisibility.return_value = True
        order = Mock()
        order.attach_mock(plugin.addon.setSetting, 'set')
        order.attach_mock(self.kodi.executebuiltin, 'run')
        plugin.dispatch()
        self.assertEqual(order.mock_calls, [
            call.set('iptv.channels_uri', 'plugin://plugin.video.odidotv/?action=iptv_channels'),
            call.set('iptv.epg_uri', 'plugin://plugin.video.odidotv/?action=iptv_epg'),
            call.set('iptv.enabled', 'true'), call.run('RunScript(service.iptv.manager,refresh)')])

    def test_disabled_manager_prevents_refresh_and_shows_actionable_message(self):
        plugin = self.plugin('?action=iptv_refresh')
        self.kodi.getCondVisibility.return_value = False
        plugin.dispatch()
        plugin.addon.setSetting.assert_not_called()
        self.kodi.executebuiltin.assert_not_called()
        plugin.dialog.ok.assert_called_once_with('Odido TV', '30079')

    def test_refresh_configures_native_instance_without_legacy_manager_setup(self):
        import xml.etree.ElementTree as ET
        plugin = self.plugin('?action=iptv_refresh')
        self.kodi.getCondVisibility.return_value = True
        plugin.dispatch()
        path = Path(self.directory.name)/'pvr/instance-settings-2.xml'
        settings = {item.get('id'): item.text or '' for item in ET.parse(path).getroot()}
        self.assertEqual(settings['m3uPathType'], '0')
        self.assertEqual(settings['m3uPath'], str(Path(self.directory.name)/'manager/playlist.m3u8'))
        self.assertEqual(settings['epgPath'], str(Path(self.directory.name)/'manager/epg.xml'))
        self.assertEqual(settings['kodi_addon_instance_enabled'], 'true')
        self.kodi.executebuiltin.assert_called_once_with('RunScript(service.iptv.manager,refresh)')

    def test_explicit_setup_shows_configured_message_and_starts_refresh(self):
        plugin = self.plugin('?action=iptv_setup')
        self.kodi.getCondVisibility.return_value = True
        plugin.dispatch()
        plugin.dialog.ok.assert_called_once_with('Odido TV', '30081')
        self.kodi.executebuiltin.assert_called_once_with('RunScript(service.iptv.manager,refresh)')

    def test_setup_enables_disabled_pvr_after_saving_instance(self):
        import json
        plugin = self.plugin('?action=iptv_setup')
        self.kodi.getCondVisibility.side_effect = lambda condition: condition != 'System.AddonIsEnabled(pvr.iptvsimple)'
        self.kodi.executeJSONRPC.return_value = '{"result":"OK"}'
        plugin.dispatch()
        request = json.loads(self.kodi.executeJSONRPC.call_args.args[0])
        self.assertEqual(request['method'], 'Addons.SetAddonEnabled')
        self.assertEqual(request['params'], {'addonid': 'pvr.iptvsimple', 'enabled': True})
        self.assertTrue((Path(self.directory.name)/'pvr/instance-settings-2.xml').is_file())

    def test_successful_callback_persists_count_after_send(self):
        from resources.lib import plugin as module
        from resources.lib.iptv import send
        from resources.lib.storage import read_json
        plugin = self.plugin('?action=iptv_channels&port=23456')
        plugin.addon.getSetting.side_effect = lambda key: {'iptv.enabled': 'true', 'iptv.selected': ''}.get(key, '')
        plugin.client.channel_rows.return_value = [{'ID': '18', 'name': 'Channel'}]
        context = Mock()
        context.__enter__ = Mock(return_value=Mock())
        context.__exit__ = Mock()
        def callback(port, kind, produce, report):
            send(port, kind, produce, report, connect=Mock(return_value=context))
        with patch.object(module, 'send_iptv', side_effect=callback):
            plugin.dispatch()
        status = read_json(Path(self.directory.name)/'iptv_export_channels.json')
        self.assertEqual((status['phase'], status['count'], status['error']), ('sent', 1, ''))

    def test_failed_callback_persists_error_without_provider_response(self):
        from resources.lib import plugin as module
        from resources.lib.storage import read_json
        plugin = self.plugin('?action=iptv_channels&port=23456')
        with patch.object(module, 'send_iptv', side_effect=ConnectionRefusedError('private URL')):
            plugin.dispatch()
        status = read_json(Path(self.directory.name)/'iptv_export_channels.json')
        self.assertEqual(status['phase'], 'error')
        self.assertIn('ConnectionRefusedError', status['error'])
        self.assertNotIn('private', str(status))
        plugin.dialog.ok.assert_not_called()

    def test_status_screen_distinguishes_missing_callbacks_and_manager_files(self):
        from resources.lib import plugin as module
        plugin = self.plugin('?action=iptv_status')
        plugin.addon.getSetting.return_value = 'true'
        self.kodi.getCondVisibility.return_value = True
        with patch.object(module.xbmcvfs, 'exists', side_effect=[True, False], create=True):
            plugin.dispatch()
        message = plugin.dialog.textviewer.call_args.args[1]
        self.assertEqual(message.count('NOT_CALLED'), 2)
        self.assertIn('30072: 30076', message)  # Playlist exists.
        self.assertIn('30073: 30077', message)  # Guide absent.

    def test_channel_picker_preserves_cancel_and_stores_explicit_selection(self):
        plugin = self.plugin('?action=iptv_select')
        plugin.addon.getSetting.return_value = ''
        plugin.client.channel_rows.return_value = [{'ID': '18', 'name': 'First'}, {'ID': '19', 'name': 'Second'}]
        plugin.dialog.multiselect.return_value = None
        plugin.dispatch()
        plugin.addon.setSetting.assert_not_called()
        plugin.dialog.multiselect.return_value = [1]
        plugin.dispatch()
        plugin.addon.setSetting.assert_called_once_with('iptv.selected', '["19"]')

    def test_native_tv_channel_link_resolves_through_working_relay(self):
        from resources.lib.iptv import playback_url
        from urllib.parse import urlparse
        plugin = self.plugin('?' + urlparse(playback_url('channel', '141430714', title='NPO 1')).query)
        plugin.handle = -1
        plugin.client.stream.return_value = {'url': 'https://example.test/signed.mpd', 'license': '', 'custom_data': ''}
        plugin.dispatch()
        plugin.client.stream.assert_called_once_with('channel', '141430714', '')
        self.assertEqual(self.kplugin.setResolvedUrl.call_args.args[:2], (-1, True))
        self.assertEqual(self.kplugin.setResolvedUrl.call_args.args[2].kwargs['path'],
                         'http://127.0.0.1:12345/secret/session/manifest.mpd')

    def test_device_limit_has_specific_guidance_without_retry(self):
        from resources.lib import plugin as module
        from resources.lib.api import OdidoError
        plugin = self.plugin('?action=login')
        plugin.dispatch = Mock(side_effect=OdidoError('DEVICE_LIMIT'))
        with patch.object(module, 'Plugin', return_value=plugin):
            module.run()
        plugin.dispatch.assert_called_once()
        self.assertEqual(plugin.dialog.ok.call_args.args[1], '30049\nDEVICE_LIMIT')

    def test_cancel_login_marks_playback_failed(self):
        from resources.lib.api import AuthError
        plugin = self.plugin('?action=play&kind=channel&id=18')
        plugin.client.logged_in = False
        plugin.client.require_session.side_effect = AuthError('LOGIN_REQUIRED')
        plugin.dialog.input.return_value = ''
        plugin.dispatch()
        plugin.client.stream.assert_not_called()
        self.assertFalse(self.kplugin.setResolvedUrl.call_args.args[1])

    def test_saved_login_avoids_customer_number_and_pin_dialogs(self):
        plugin = self.plugin('?action=live')
        plugin.client.logged_in = False
        self.assertTrue(plugin.require_login())
        plugin.client.require_session.assert_called_once()
        plugin.dialog.input.assert_not_called()
        plugin.dialog.ok.assert_not_called()

    def test_expired_session_still_offers_sign_out_to_forget_login(self):
        plugin = self.plugin('?action=root')
        plugin.client.logged_in = False
        plugin.client.state = {'credentials': {'username': 'customer', 'pin': '0012'}}
        plugin.dispatch()
        urls = [call.args[1] for call in self.kplugin.addDirectoryItem.call_args_list]
        self.assertTrue(any('action=login' in url for url in urls))
        self.assertTrue(any('action=logout' in url for url in urls))

    def test_diagnostics_exclude_saved_credentials(self):
        plugin = self.plugin('?action=diagnostics')
        plugin.client.state = {'credentials': {'username': 'private-user', 'pin': '0012'}}
        self.kodi.getInfoLabel.return_value = '21.2'
        self.gui.Window.return_value.getProperty.return_value = ''
        plugin.dispatch()
        text = (Path(plugin.profile) / 'diagnostics.json').read_text()
        self.assertNotIn('credentials', text)
        self.assertNotIn('private-user', text)
        self.assertNotIn('0012', text)

    def test_widevine_headers_passed_only_to_license(self):
        plugin = self.plugin('?action=play&kind=program&id=77&channel=18')
        plugin.client.stream.return_value = {'url': 'https://cdn.example/a.mpd?sig=x%2By',
                                             'license': 'https://tv.odido.nl/license', 'custom_data': 'opaque'}
        plugin.client.media_headers.side_effect = [{'User-Agent': 'test'}, {'AcquireLicense.CustomData': 'opaque'}]
        plugin.dispatch()
        plugin.client.stream.assert_called_once_with('program', '77', '18')
        self.kplugin.setResolvedUrl.assert_called_once()
        item = self.kplugin.setResolvedUrl.call_args.args[2]
        self.assertEqual(item.kwargs['path'], 'http://127.0.0.1:12345/secret/session/manifest.mpd')
        props = dict(call.args for call in item.setProperty.call_args_list)
        self.assertIn('/session/license|Content-Type=', props['inputstream.adaptive.license_key'])
        self.assertNotIn('opaque', str(props))
        self.assertNotIn('sig=x%2By', str(props))
        self.assertEqual(self.register.call_args.args[1]['custom_data'], 'opaque')
        plugin.client.media_headers.assert_not_called()
        self.assertTrue(props['inputstream.adaptive.license_key'].endswith('|R{SSM}|'))

    def test_clear_stream_does_not_require_widevine(self):
        plugin = self.plugin('?action=play&kind=channel&id=18')
        plugin.client.stream.return_value = {'url': 'https://cdn.example/clear.mpd', 'license': '', 'custom_data': ''}
        plugin.client.media_headers.return_value = {}
        plugin.dispatch()
        self.helper.Helper.assert_not_called()
        self.assertTrue(self.kplugin.setResolvedUrl.call_args.args[1])

    def test_live_modes_use_same_stream_and_set_inputstream_start_position(self):
        for mode, value in (('begin', 'true'), ('live', 'false')):
            plugin = self.plugin('?action=play&kind=channel&id=18&start=' + mode)
            plugin.client.stream.return_value = {'url': 'https://example.test/live.mpd', 'license': '', 'custom_data': ''}
            plugin.dispatch()
            plugin.client.stream.assert_called_once_with('channel', '18', '')
            self.kplugin.setResolvedUrl.call_args.args[2].setProperty.assert_any_call(
                'inputstream.adaptive.play_timeshift_buffer', value)

    def test_current_programme_opens_channel_buffer_without_replay_request(self):
        from resources.lib import plugin as module
        plugin = self.plugin('?action=play&kind=program&id=77&channel=18&programme_start=1000&programme_end=3000')
        plugin.client.stream.return_value = {'url': 'https://example.test/live.mpd', 'license': '', 'custom_data': ''}
        with patch.object(module.time, 'time', return_value=2):
            plugin.dispatch()
        plugin.client.stream.assert_called_once_with('channel', '18', '')
        self.kplugin.setResolvedUrl.call_args.args[2].setProperty.assert_any_call(
            'inputstream.adaptive.play_timeshift_buffer', 'true')

    def test_skin_integration_registers_copy_and_selects_it_using_kodi_settings(self):
        import json
        from resources.lib import plugin as module
        plugin = self.plugin('?action=tv_skin')
        self.kodi.getSkinDir.return_value = 'skin.estuary'
        self.kodi.executeJSONRPC.side_effect = ['{"result":"OK"}', '{"result":true}']
        with patch.object(module, 'install_tv_skin') as installer:
            plugin.dispatch()
        installer.assert_called_once()
        self.kodi.executebuiltin.assert_called_once_with('UpdateLocalAddons()', True)
        requests = [json.loads(call.args[0]) for call in self.kodi.executeJSONRPC.call_args_list]
        self.assertEqual(requests[0]['params'], {'addonid': 'skin.estuary.odidotv', 'enabled': True})
        self.assertEqual(requests[1]['params'], {'setting': 'lookandfeel.skin', 'value': 'skin.estuary.odidotv'})
        self.gui.DialogProgress.return_value.close.assert_called_once()

    def test_other_skin_is_not_silently_replaced(self):
        from resources.lib import plugin as module
        plugin = self.plugin('?action=tv_skin')
        self.kodi.getSkinDir.return_value = 'skin.other'
        with patch.object(module, 'install_tv_skin') as installer:
            plugin.dispatch()
        installer.assert_not_called()
        self.kodi.executeJSONRPC.assert_not_called()
        plugin.dialog.ok.assert_called_once_with('Odido TV', '30096')

    def test_standard_skin_restore_does_not_copy_or_delete_skins(self):
        import json
        from resources.lib import plugin as module
        plugin = self.plugin('?action=tv_skin_restore')
        self.kodi.executeJSONRPC.return_value = '{"result":true}'
        with patch.object(module, 'install_tv_skin') as installer:
            plugin.dispatch()
        installer.assert_not_called()
        request = json.loads(self.kodi.executeJSONRPC.call_args.args[0])
        self.assertEqual(request['params'], {'setting': 'lookandfeel.skin', 'value': 'skin.estuary'})

    def test_channel_context_menu_has_both_live_positions(self):
        plugin = self.plugin('?action=live')
        plugin.client.channels.return_value = [channel()]
        plugin.client.live_programmes.return_value = ([], [])
        plugin.dispatch()
        contexts = self.items[0].addContextMenuItems.call_args.args[0]
        self.assertTrue(any('start=live' in command and command.startswith('PlayMedia(') for _, command in contexts))
        self.assertTrue(any('start=begin' in command and command.startswith('PlayMedia(') for _, command in contexts))

    def test_widevine_unavailable_reports_failure(self):
        plugin = self.plugin('?action=play&kind=channel&id=18')
        plugin.client.stream.return_value = {'url': 'https://cdn.example/a.mpd', 'license': 'https://tv.odido.nl/license', 'custom_data': ''}
        self.helper.Helper.return_value.check_inputstream.return_value = False
        plugin.dispatch()
        self.assertFalse(self.kplugin.setResolvedUrl.call_args.args[1])

    def test_future_program_not_playable(self):
        plugin = self.plugin('?action=guide&channel=18&day=20261017')
        plugin.client.day.return_value = [dict(channel(), kind='program', start=9999999999999)]
        plugin.dispatch()
        self.items[0].setProperty.assert_any_call('IsPlayable', 'false')

    def test_replay_channel_and_day_navigation_preserves_channel_id(self):
        from urllib.parse import parse_qs, urlparse
        plugin = self.plugin('?action=replay')
        plugin.client.channels.return_value = [dict(channel(), id='141430714')]
        plugin.dispatch()
        query = parse_qs(urlparse(self.kplugin.addDirectoryItem.call_args.args[1]).query)
        self.assertEqual(query, {'action': ['days'], 'channel': ['141430714']})
        plugin = self.plugin('?action=days&channel=141430714')
        self.kplugin.addDirectoryItem.reset_mock()
        plugin.dispatch()
        calls = self.kplugin.addDirectoryItem.call_args_list
        self.assertEqual(len(calls), 7)
        for call in calls:
            query = parse_qs(urlparse(call.args[1]).query)
            self.assertEqual(query['action'], ['guide'])
            self.assertEqual(query['channel'], ['141430714'])
            self.assertEqual(len(query['day'][0]), 8)

    def test_replay_error_is_available_in_diagnostics(self):
        from resources.lib import plugin as module
        from resources.lib.api import OdidoError
        plugin = self.plugin('?action=guide&channel=18&day=20260606')
        plugin.dispatch = Mock(side_effect=OdidoError('API_123_GUIDE'))
        with patch.object(module, 'Plugin', return_value=plugin):
            module.run()
        self.gui.Window.return_value.setProperty.assert_called_with(
            'plugin.video.odidotv.last_guide_error', 'API_123_GUIDE')

    def test_internal_guide_error_reports_location_without_private_message(self):
        from resources.lib import plugin as module
        plugin = self.plugin('?action=guide&channel=18&day=20260606')
        plugin.client.day.side_effect = TypeError('private response or URL')
        with patch.object(module, 'Plugin', return_value=plugin):
            module.run()
        message = plugin.dialog.ok.call_args.args[1]
        self.assertRegex(message, r'^30052\nTypeError_PLUGIN_L\d+$')
        self.assertNotIn('private', message)
        self.assertFalse(self.kplugin.endOfDirectory.call_args.kwargs['succeeded'])

    def test_channel_search_is_case_insensitive(self):
        plugin = self.plugin('?action=search')
        plugin.client.channels.return_value = [channel()]
        plugin.dialog.input.return_value = 'CHANNEL'
        plugin.dispatch()
        self.kplugin.addDirectoryItem.assert_called_once()

    def test_heartbeat_ownership_excludes_other_video(self):
        spec = importlib.util.spec_from_file_location('odido_service', ROOT / 'plugin.video.odidotv/service.py')
        service = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(service)
        self.assertTrue(service.is_our_playback(True, 'https://cdn.example/a.mpd', 'https://cdn.example/a.mpd'))
        self.assertFalse(service.is_our_playback(True, 'https://other.example/b.mpd', 'https://cdn.example/a.mpd'))
        self.assertFalse(service.is_our_playback(False, '', 'https://cdn.example/a.mpd'))

    def test_service_runs_guide_maintenance_without_opening_addon_or_playing(self):
        spec = importlib.util.spec_from_file_location('odido_service', ROOT / 'plugin.video.odidotv/service.py')
        service = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(service)
        self.kodi.Monitor.return_value.abortRequested.return_value = False
        self.kodi.Monitor.return_value.waitForAbort.return_value = True
        self.kodi.Player.return_value.isPlayingVideo.return_value = False
        with patch.object(service, 'GuideRefresh') as guide, patch.object(service, 'Server'), patch.object(service.threading, 'Thread'):
            service.run()
            guide.return_value.tick.assert_called_once()
        self.gui.Dialog.assert_not_called()
        self.kodi.executebuiltin.assert_not_called()


if __name__ == '__main__':
    unittest.main()
