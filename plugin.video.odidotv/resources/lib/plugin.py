"""Kodi 21 navigation and playback. All provider requests live in api.py."""
import datetime as dt
import json
import os
import sys
from urllib.parse import parse_qs, urlencode

import xbmc
import xbmcaddon
import xbmcgui
import xbmcplugin
import xbmcvfs

from .api import Client, OdidoError, AuthError
from .storage import SavedLists, write_json
from .tvtime import local_time
from .relay import PROPERTY as RELAY_PROPERTY, RelayError, register_playback

STRINGS = {'live': 30001, 'replay': 30002, 'search': 30005, 'favorites': 30006,
           'later': 30007, 'login': 30008, 'logout': 30009, 'settings': 30010,
           'diagnostics': 30011, 'empty': 30012, 'number': 30015, 'pin': 30016,
           'login_ok': 30017, 'login_needed': 30018, 'failed': 30020,
           'add_favorites': 30021, 'add_later': 30022, 'remove': 30023, 'saved': 30024,
           'today': 30025, 'drm_missing': 30026, 'expired': 30027, 'signed_out': 30028,
           'saved_diag': 30030, 'not_yet': 30032, 'partial_guide': 30035,
           'device_limit': 30049, 'relay_unavailable': 30050, 'playback_error': 30051,
           'internal_error': 30052}
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
            if self.params.get('action') == 'saved':
                contexts.append((self.tr('remove'), 'RunPlugin(%s)' % self.url(
                    'remove', list=self.params['list'], record=encoded)))
            item.addContextMenuItems(contexts)
        if not folder:
            item.setProperty('IsPlayable', 'true' if action == 'play' else 'false')
        xbmcplugin.addDirectoryItem(self.handle, self.url(action, **params), item, isFolder=folder)

    def content_entry(self, record, label=None):
        self.entry(label or record['title'], 'play', folder=False, record=record,
                   kind=record['kind'], id=record['id'], channel=record.get('channel', ''),
                   title=record['title'])

    def root(self):
        for key in ('live', 'replay', 'search'):
            self.entry(self.tr(key), key)
        for key in ('favorites', 'later'):
            self.entry(self.tr(key), 'saved', list=key)
        for key in (('logout',) if self.client.logged_in else ('login',)) + ('settings', 'diagnostics'):
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
        stream = self.client.stream(self.params['kind'], self.params['id'], self.params.get('channel', ''))
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
        if stream['license']:
            item.setProperty('inputstream.adaptive.license_type', 'com.widevine.alpha')
            item.setProperty('inputstream.adaptive.license_key',
                             local['license'] + '|Content-Type=application%2Foctet-stream|R{SSM}|')
        # Only memory, never persist the signed manifest to disk.
        window.setProperty(PLAYING_PROPERTY, local['url'])
        xbmcplugin.setResolvedUrl(self.handle, True, item)

    def dispatch(self):
        action = self.params.get('action', 'root')
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
            write_json(path, {'addon_version': self.addon.getAddonInfo('version'),
                             'kodi_version': xbmc.getInfoLabel('System.BuildVersion'),
                             'session_saved': self.client.logged_in, 'last_playback_error': last_error,
                             'last_guide_error': guide_error})
            self.dialog.ok('Odido TV', self.tr('saved_diag') + '\n' + path +
                           ('\n' + self.tr('playback_error') + ': ' + last_error if last_error else ''))
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
                                'device_limit' if code == 'DEVICE_LIMIT' else
                                'expired' if isinstance(error, AuthError) else
                                'internal_error' if not isinstance(error, (OdidoError, RelayError)) else 'failed')
            plugin.dialog.ok('Odido TV', message + '\n' + code)
            if plugin.params.get('action') == 'play':
                xbmcplugin.setResolvedUrl(plugin.handle, False, xbmcgui.ListItem())
            elif plugin.params.get('action', 'root') in ('root', 'live', 'replay', 'days', 'guide', 'search', 'saved'):
                plugin.finish(False)
