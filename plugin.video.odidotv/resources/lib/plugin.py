"""Kodi 21 navigation and playback. All provider requests live in api.py."""
import datetime as dt
import json
import os
import sys
import time
from urllib.parse import parse_qs, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from .api import Client, OdidoError, AuthError
from .storage import SavedLists, read_json, write_json
from .tvtime import local_time
from .iptv import Exporter, selection, send as send_iptv
from .pvr import configure as configure_pvr
from .playmode import target as playback_target
from .tvskin import install as install_tv_skin, SKIN_ID
from .relay import PROPERTY as RELAY_PROPERTY, RelayError, register_playback

STRINGS = {'live': 30001, 'replay': 30002, 'search': 30005, 'favorites': 30006,
           'later': 30007, 'login': 30008, 'logout': 30009, 'settings': 30010,
           'diagnostics': 30011, 'empty': 30012, 'number': 30015, 'pin': 30016,
           'login_ok': 30017, 'login_needed': 30018, 'failed': 30020,
           'add_favorites': 30021, 'add_later': 30022, 'remove': 30023, 'saved': 30024,
           'today': 30025, 'drm_missing': 30026, 'expired': 30027, 'signed_out': 30028,
           'saved_diag': 30030, 'not_yet': 30032, 'partial_guide': 30035,
           'device_limit': 30049, 'relay_unavailable': 30050, 'playback_error': 30051,
           'internal_error': 30052, 'iptv_channels': 30062,
           'iptv_check': 30071, 'iptv_enabled': 30061, 'iptv_playlist': 30072,
           'iptv_guide': 30073, 'iptv_channels_callback': 30074, 'iptv_epg_callback': 30075,
           'yes': 30076, 'no': 30077, 'iptv_error': 30078, 'iptv_manager_missing': 30079,
           'pvr_missing': 30080, 'pvr_configured': 30081, 'pvr_instance': 30082,
           'buffer_start': 30084, 'watch_live': 30087, 'not_started': 30091,
           'no_replay': 30092, 'skin_preparing': 30094, 'skin_unsupported': 30096}
PLAYING_PROPERTY = 'plugin.video.odidotv.manifest'


def error_code(error):
    if isinstance(error, (OdidoError, RelayError)):
        return str(error)
    code = type(error).__name__
    # Only source basename and line number: no exception messages, locals or URLs.
    frame = error.__traceback__
    root = os.path.dirname(__file__) + os.sep
    while frame:
        filename = frame.tb_frame.f_code.co_filename
        if os.path.abspath(filename).startswith(root):
            name = os.path.splitext(os.path.basename(filename))[0]
            code = type(error).__name__ + '_' + name.upper() + '_L' + str(frame.tb_lineno)
        frame = frame.tb_next
    return code


class Plugin:
    def __init__(self, argv):
        self.base, self.handle = argv[0], int(argv[1])
        self.params = {key: value[0] for key, value in parse_qs(argv[2].lstrip('?')).items()}
        self.addon = xbmcaddon.Addon()
        self.profile = xbmcvfs.translatePath(self.addon.getAddonInfo('profile'))
        self.client = Client(self.profile, device_name=self.addon.getSetting('device_name'))
        self.lists = SavedLists(self.profile)
        self.dialog = xbmcgui.Dialog()

    def tr(self, key):
        return self.addon.getLocalizedString(STRINGS[key])

    def url(self, action, **params):
        return self.base + '?' + urlencode(dict(action=action, **params))

    def notify(self, key):
        self.dialog.notification('Odido TV', self.tr(key), xbmcgui.NOTIFICATION_INFO)

    def finish(self, succeeded=True):
        xbmcplugin.endOfDirectory(self.handle, succeeded=succeeded, cacheToDisc=False)

    def entry(self, label, action, folder=True, record=None, **params):
        item = xbmcgui.ListItem(label=label)
        if record:
            info = item.getVideoInfoTag()
            info.setTitle(record['title'])
            info.setPlot(record.get('plot', ''))
            info.setMediaType('video')
            if record.get('duration'):
                info.setDuration(record['duration'])
            item.setArt({'thumb': record.get('image', ''), 'fanart': record.get('image', '')})
            encoded = json.dumps(record, ensure_ascii=False)
            contexts = [(self.tr('add_favorites'), 'RunPlugin(%s)' % self.url(
                'save', list='favorites', record=encoded))]
            if record['kind'] == 'program':
                contexts.append((self.tr('add_later'), 'RunPlugin(%s)' % self.url(
                    'save', list='later', record=encoded)))
            elif record['kind'] == 'channel':
                for mode, label in (('live', 'watch_live'), ('begin', 'buffer_start')):
                    contexts.append((self.tr(label), 'PlayMedia(%s)' % self.url(
                        'play', kind='channel', id=record['id'], title=record['title'], start=mode)))
            if self.params.get('action') == 'saved':
                contexts.append((self.tr('remove'), 'RunPlugin(%s)' % self.url(
                    'remove', list=self.params['list'], record=encoded)))
            item.addContextMenuItems(contexts)
        if not folder:
            item.setProperty('IsPlayable', 'true' if action == 'play' else 'false')
        xbmcplugin.addDirectoryItem(self.handle, self.url(action, **params), item, isFolder=folder)

    def content_entry(self, record, label=None):
        bounds = {}
        if record['kind'] == 'program' and record.get('start', 0) > 0 and record.get('end', 0) > record['start']:
            bounds = {'programme_start': record['start'], 'programme_end': record['end']}
        self.entry(label or record['title'], 'play', folder=False, record=record,
                   kind=record['kind'], id=record['id'], channel=record.get('channel', ''),
                   title=record['title'], **bounds)

    def root(self):
        for key in ('live', 'replay', 'search'):
            self.entry(self.tr(key), key)
        for key in ('favorites', 'later'):
            self.entry(self.tr(key), 'saved', list=key)
        account_actions = ('logout',) if self.client.logged_in else ('login',)
        if not self.client.logged_in and self.client.state.get('credentials'):
            account_actions += ('logout',)
        for key in account_actions + ('settings', 'diagnostics'):
            self.entry(self.tr(key), key, folder=False)
        self.finish()

    def login(self):
        username = self.dialog.input(self.tr('number')).strip()
        if not username:
            return False
        pin = self.dialog.input(self.tr('pin'), type=xbmcgui.INPUT_ALPHANUM,
                                option=xbmcgui.ALPHANUM_HIDE_INPUT)
        if not pin:
            return False
        self.client.login(username, pin)
        self.notify('login_ok')
        return True

    def require_login(self):
        if self.client.logged_in:
            return True
        try:
            self.client.require_session()
            return True
        except AuthError as error:
            if str(error) != 'LOGIN_REQUIRED':
                raise
        self.dialog.ok('Odido TV', self.tr('login_needed'))
        return self.login()

    def live(self):
        rows = self.client.channels()
        current = {}
        try:
            programmes, errors = self.client.live_programmes([row['id'] for row in rows])
            current = {row['channel']: row for row in programmes}
        except OdidoError as error:
            errors = [str(error)]
        if errors:
            code = errors[0]
            xbmcgui.Window(10000).setProperty('plugin.video.odidotv.last_guide_error', code)
            self.dialog.notification('Odido TV', self.tr('partial_guide') + '\n' + code,
                                     xbmcgui.NOTIFICATION_INFO)
        else:
            xbmcgui.Window(10000).clearProperty('plugin.video.odidotv.last_guide_error')
        for row in rows:
            program = current.get(row['id'])
            label = row['title'] + (' — ' + program['title'] if program else '')
            if program:
                row['plot'] = program['plot']
            self.content_entry(row, label)
        if not rows:
            self.notify('empty')
        xbmcplugin.setContent(self.handle, 'videos')
        self.finish()

    def replay(self):
        for row in self.client.channels():
            self.entry(row['title'], 'days', channel=row['id'])
        self.finish()

    def days(self):
        for offset in range(7):
            date = local_time().date() - dt.timedelta(days=offset)
            self.entry(self.tr('today') if offset == 0 else date.strftime('%a %d-%m-%Y'),
                       'guide', channel=self.params['channel'], day=date.strftime('%Y%m%d'))
        self.finish()

    def guide(self):
        rows = sorted(self.client.day(self.params['channel'], self.params['day']), key=lambda r: r['start'])
        window = xbmcgui.Window(10000)
        if rows:
            window.clearProperty('plugin.video.odidotv.last_guide_error')
        else:
            window.setProperty('plugin.video.odidotv.last_guide_error', 'GUIDE_EMPTY')
        now = dt.datetime.now().timestamp() * 1000
        for row in rows:
            label = local_time(row['start'] / 1000).strftime('%H:%M') + ' — ' + row['title']
            if row['start'] > now:
                self.entry(label + ' (' + self.tr('not_yet') + ')', 'unavailable', folder=False)
            else:
                self.content_entry(row, label)
        if not rows:
            self.notify('empty')
        xbmcplugin.setContent(self.handle, 'episodes')
        self.finish()

    def iptv_select(self):
        if not self.require_login():
            return
        rows = self.client.channel_rows()
        selected = selection(self.addon.getSetting('iptv.selected'))
        indices = self.dialog.multiselect(self.tr('iptv_channels'), [row['name'] for row in rows],
                                         preselect=[index for index, row in enumerate(rows)
                                                    if selected is None or str(row['ID']) in selected])
        if indices is not None:
            self.addon.setSetting('iptv.selected', json.dumps([str(rows[index]['ID']) for index in indices]))

    def iptv_export(self, kind):
        status_path = os.path.join(self.profile, 'iptv_export_' + kind + '.json')
        status = {'phase': 'started', 'count': 0, 'error': '', 'updated': int(time.time())}
        def save_status():
            status['updated'] = int(time.time())
            write_json(status_path, status)

        save_status()
        def report(error):
            code = error_code(error)
            status['error'] = code
            status['phase'] = 'error'
            save_status()
            xbmcgui.Window(10000).setProperty('plugin.video.odidotv.last_iptv_error', code)
            xbmc.log('[plugin.video.odidotv] IPTV_' + code, xbmc.LOGWARNING)

        def produce():
            window = xbmcgui.Window(10000)
            window.clearProperty('plugin.video.odidotv.last_iptv_error')
            if self.addon.getSetting('iptv.enabled') != 'true':
                status['phase'] = 'disabled'
                save_status()
                return {'version': 1, 'streams': []} if kind == 'channels' else {'version': 1, 'epg': {}}
            if kind == 'epg':
                # Validate/renew an expired saved session before guide requests.
                # Background imports must never open sign-in dialogs.
                try:
                    self.client.heartbeat()
                except OdidoError:
                    if not self.client.logged_in:
                        raise
                    # A temporary outage must still allow cached EPG export.
            exporter = Exporter(self.client, selection(self.addon.getSetting('iptv.selected')),
                                cancelled=xbmc.Monitor().abortRequested)
            if kind == 'channels':
                result = exporter.channels()
                status.update(phase='ready', count=len(result['streams']))
                save_status()
                return result
            try:
                days = int(self.addon.getSetting('iptv.days') or '7')
            except ValueError:
                raise OdidoError('IPTV_INVALID_DAYS') from None
            result = exporter.epg(days)
            if exporter.errors:
                report(OdidoError(exporter.errors[0]))
            status.update(phase='ready', count=sum(map(len, result['epg'].values())))
            save_status()
            return result

        try:
            send_iptv(self.params.get('port'), kind, produce, report)
            if status['phase'] == 'ready':
                status['phase'] = 'sent'
                save_status()
        except Exception as error:
            # Manager runs callbacks in the background, often with handle -1.
            # Never open login/error dialogs or resolve/end a directory here.
            report(error)

    def iptv_refresh(self, setup=False):
        if not self.require_login():
            return
        if not xbmc.getCondVisibility('System.AddonIsEnabled(service.iptv.manager)'):
            self.dialog.ok('Odido TV', self.tr('iptv_manager_missing'))
            return
        if not xbmc.getCondVisibility('System.HasAddon(pvr.iptvsimple)'):
            self.dialog.ok('Odido TV', self.tr('pvr_missing'))
            return
        pvr = xbmcaddon.Addon('pvr.iptvsimple')
        manager = xbmcaddon.Addon('service.iptv.manager')
        manager_profile = xbmcvfs.translatePath(manager.getAddonInfo('profile'))
        try:
            instance, changed = configure_pvr(xbmcvfs.translatePath(pvr.getAddonInfo('profile')),
                                              os.path.join(manager_profile, 'playlist.m3u8'),
                                              os.path.join(manager_profile, 'epg.xml'), xbmcvfs.translatePath)
        except ValueError:
            raise OdidoError('IPTV_PVR_MIGRATE_FIRST') from None
        write_json(os.path.join(self.profile, 'iptv_pvr.json'), {'instance': instance})
        # Ensure a PVR instance written while the addon was disabled is loaded.
        if not xbmc.getCondVisibility('System.AddonIsEnabled(pvr.iptvsimple)'):
            result = json.loads(xbmc.executeJSONRPC(json.dumps({
                'jsonrpc': '2.0', 'id': 1, 'method': 'Addons.SetAddonEnabled',
                'params': {'addonid': 'pvr.iptvsimple', 'enabled': True}})))
            if 'error' in result:
                raise OdidoError('IPTV_PVR_ENABLE_FAILED')
        if setup:
            self.dialog.ok('Odido TV', self.tr('pvr_configured'))
        # Persist discovery before Manager scans, including when the settings
        # dialog's enable toggle has not yet been saved.
        self.addon.setSetting('iptv.channels_uri', 'plugin://plugin.video.odidotv/?action=iptv_channels')
        self.addon.setSetting('iptv.epg_uri', 'plugin://plugin.video.odidotv/?action=iptv_epg')
        self.addon.setSetting('iptv.enabled', 'true')
        xbmc.executebuiltin('RunScript(service.iptv.manager,refresh)')

    def iptv_status(self):
        def yesno(value):
            return self.tr('yes' if value else 'no')
        def callback(kind):
            value = read_json(os.path.join(self.profile, 'iptv_export_' + kind + '.json'), {})
            if not isinstance(value, dict) or not value:
                return 'NOT_CALLED'
            phase = value.get('phase', 'unknown')
            count = value.get('count', 0)
            code = value.get('error', '')
            return str(phase).upper() + ' (' + str(count) + ')' + (' / ' + code if code else '')
        lines = [self.tr('iptv_enabled') + ': ' + yesno(self.addon.getSetting('iptv.enabled') == 'true'),
                 'IPTV Manager: ' + yesno(xbmc.getCondVisibility('System.AddonIsEnabled(service.iptv.manager)')),
                 'IPTV Simple: ' + yesno(xbmc.getCondVisibility('System.AddonIsEnabled(pvr.iptvsimple)')),
                 self.tr('iptv_channels_callback') + ': ' + callback('channels'),
                 self.tr('iptv_epg_callback') + ': ' + callback('epg'),
                 self.tr('iptv_playlist') + ': ' + yesno(xbmcvfs.exists('special://profile/addon_data/service.iptv.manager/playlist.m3u8')),
                 self.tr('iptv_guide') + ': ' + yesno(xbmcvfs.exists('special://profile/addon_data/service.iptv.manager/epg.xml'))]
        native = read_json(os.path.join(self.profile, 'iptv_pvr.json'), {})
        filename = native.get('instance', '') if isinstance(native, dict) else ''
        lines.append(self.tr('pvr_instance') + ': ' + (filename or 'NOT_CONFIGURED'))
        self.dialog.textviewer(self.tr('iptv_check'), '\n'.join(lines))

    def tv_skin(self, restore=False):
        if restore:
            skin = 'skin.estuary'
        else:
            if xbmc.getSkinDir() not in ('skin.estuary', SKIN_ID):
                self.dialog.ok('Odido TV', self.tr('skin_unsupported'))
                return
            progress = xbmcgui.DialogProgress()
            progress.create('Odido TV', self.tr('skin_preparing'))
            monitor = xbmc.Monitor()
            try:
                source = xbmcaddon.Addon('skin.estuary').getAddonInfo('path')
                install_tv_skin(xbmcvfs, source, xbmcvfs.translatePath('special://home/addons/'),
                                cancelled=lambda: progress.iscanceled() or monitor.abortRequested())
            except ValueError as error:
                code = str(error)
                raise OdidoError(code if code.startswith('SKIN_') and code.replace('_', '').isalnum() else 'SKIN_SETUP_FAILED') from None
            finally:
                progress.close()
            xbmc.executebuiltin('UpdateLocalAddons()', True)
            result = json.loads(xbmc.executeJSONRPC(json.dumps({
                'jsonrpc': '2.0', 'id': 1, 'method': 'Addons.SetAddonEnabled',
                'params': {'addonid': SKIN_ID, 'enabled': True}})))
            if 'error' in result:
                raise OdidoError('SKIN_ENABLE_FAILED')
            skin = SKIN_ID
        # Kodi handles its normal "keep this skin?" dialog and rollback.
        result = json.loads(xbmc.executeJSONRPC(json.dumps({
            'jsonrpc': '2.0', 'id': 1, 'method': 'Settings.SetSettingValue',
            'params': {'setting': 'lookandfeel.skin', 'value': skin}})))
        if 'error' in result or result.get('result') is not True:
            raise OdidoError('SKIN_SELECT_FAILED')

    def search(self):
        # Explicit channel-title search; no speculative VOD search endpoint.
        query = self.dialog.input(self.tr('search')).strip().casefold()
        rows = [row for row in self.client.channels() if query and query in row['title'].casefold()] if query else []
        for row in rows:
            self.content_entry(row)
        if query and not rows:
            self.notify('empty')
        self.finish()

    def saved(self):
        rows = self.lists.items(self.params['list'])
        for row in rows:
            self.content_entry(row)
        if not rows:
            self.notify('empty')
        self.finish()

    def play(self):
        default = 'begin' if self.addon.getSetting('live_start') == '1' else 'live'
        kind, identifier, channel, mode = playback_target(self.params, default, time.time() * 1000)
        stream = self.client.stream(kind, identifier, channel)
        if stream['license']:
            import inputstreamhelper
            if not inputstreamhelper.Helper('mpd', drm='com.widevine.alpha').check_inputstream():
                self.dialog.ok('Odido TV', self.tr('drm_missing'))
                xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
                return
        window = xbmcgui.Window(10000)
        window.clearProperty('plugin.video.odidotv.last_playback_error')
        monitor = xbmc.Monitor()
        base = window.getProperty(RELAY_PROPERTY)
        for _ in range(10):
            if base:
                break
            if monitor.waitForAbort(0.5):
                raise RelayError('RELAY_NOT_AVAILABLE')
            base = window.getProperty(RELAY_PROPERTY)
        local = register_playback(base, stream)
        item = xbmcgui.ListItem(path=local['url'])
        item.setContentLookup(False)
        item.setMimeType('application/dash+xml')
        item.getVideoInfoTag().setTitle(self.params.get('title', 'Odido TV'))
        item.setProperty('inputstream', 'inputstream.adaptive')
        item.setProperty('inputstream.adaptive.manifest_type', 'mpd')
        if kind == 'channel':
            item.setProperty('inputstream.adaptive.play_timeshift_buffer', 'true' if mode == 'begin' else 'false')
        if stream['license']:
            item.setProperty('inputstream.adaptive.license_type', 'com.widevine.alpha')
            item.setProperty('inputstream.adaptive.license_key',
                             local['license'] + '|Content-Type=application%2Foctet-stream|R{SSM}|')
        # Only memory, never persist the signed manifest to disk.
        window.setProperty(PLAYING_PROPERTY, local['url'])
        xbmcplugin.setResolvedUrl(self.handle, True, item)

    def dispatch(self):
        action = self.params.get('action', 'root')
        if action in ('iptv_channels', 'iptv_epg'):
            self.iptv_export('channels' if action == 'iptv_channels' else 'epg')
            return
        if action == 'iptv_select':
            self.iptv_select()
            return
        if action == 'iptv_all':
            self.addon.setSetting('iptv.selected', '')
            return
        if action == 'iptv_status':
            self.iptv_status()
            return
        if action == 'iptv_refresh':
            self.iptv_refresh()
            return
        if action == 'iptv_setup':
            self.iptv_refresh(setup=True)
            return
        if action in ('tv_skin', 'tv_skin_restore'):
            self.tv_skin(restore=action == 'tv_skin_restore')
            return
        if action in ('live', 'replay', 'guide', 'search', 'play') and not self.require_login():
            if action == 'play':
                xbmcplugin.setResolvedUrl(self.handle, False, xbmcgui.ListItem())
            else:
                self.finish(False)
            return
        if action in ('root', 'live', 'replay', 'days', 'guide', 'search', 'saved', 'play'):
            getattr(self, action)()
        elif action == 'login':
            self.login()
            xbmc.executebuiltin('Container.Refresh')
        elif action == 'logout':
            self.client.logout()
            xbmcgui.Window(10000).clearProperty(PLAYING_PROPERTY)
            self.notify('signed_out')
            xbmc.executebuiltin('Container.Refresh')
        elif action in ('save', 'remove'):
            row = json.loads(self.params['record'])
            # Whitelist content metadata; never save play URLs or arbitrary fields.
            fields = ('kind', 'id', 'channel', 'title', 'plot', 'image', 'duration', 'start', 'end')
            row = {key: row[key] for key in fields if key in row}
            if row.get('kind') not in ('channel', 'program'):
                raise OdidoError('INVALID_SAVED_ITEM')
            self.lists.update(self.params['list'], row, remove=action == 'remove')
            self.notify('saved')
            xbmc.executebuiltin('Container.Refresh')
        elif action == 'settings':
            self.addon.openSettings()
        elif action == 'diagnostics':
            path = os.path.join(self.profile, 'diagnostics.json')
            last_error = xbmcgui.Window(10000).getProperty('plugin.video.odidotv.last_playback_error')
            guide_error = xbmcgui.Window(10000).getProperty('plugin.video.odidotv.last_guide_error')
            iptv_error = xbmcgui.Window(10000).getProperty('plugin.video.odidotv.last_iptv_error')
            write_json(path, {'addon_version': self.addon.getAddonInfo('version'),
                             'kodi_version': xbmc.getInfoLabel('System.BuildVersion'),
                             'session_saved': self.client.logged_in, 'last_playback_error': last_error,
                             'last_guide_error': guide_error, 'last_iptv_error': iptv_error})
            self.dialog.ok('Odido TV', self.tr('saved_diag') + '\n' + path +
                           ('\n' + self.tr('playback_error') + ': ' + last_error if last_error else '') +
                           ('\n' + self.tr('iptv_error') + ': ' + iptv_error if iptv_error else ''))
        elif action == 'unavailable':
            self.notify('not_yet')
        else:
            raise OdidoError('UNKNOWN_ACTION')


def run():
    plugin = None
    try:
        plugin = Plugin(sys.argv)
        plugin.dispatch()
    except Exception as error:
        code = error_code(error)
        xbmc.log('[plugin.video.odidotv] ' + code, xbmc.LOGERROR)
        if plugin:
            if plugin.params.get('action') == 'guide':
                xbmcgui.Window(10000).setProperty('plugin.video.odidotv.last_guide_error', code)
            message = plugin.tr('relay_unavailable' if code.startswith('RELAY_') else
                                'not_started' if code == 'PROGRAMME_NOT_STARTED' else
                                'no_replay' if code == 'REPLAY_UNAVAILABLE' else
                                'device_limit' if code == 'DEVICE_LIMIT' else
                                'expired' if isinstance(error, AuthError) else
                                'internal_error' if not isinstance(error, (OdidoError, RelayError)) else 'failed')
            plugin.dialog.ok('Odido TV', message + '\n' + code)
            if plugin.params.get('action') == 'play':
                xbmcplugin.setResolvedUrl(plugin.handle, False, xbmcgui.ListItem())
            elif plugin.params.get('action', 'root') in ('root', 'live', 'replay', 'days', 'guide', 'search', 'saved'):
                plugin.finish(False)
