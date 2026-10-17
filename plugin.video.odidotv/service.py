"""Keep the Odido session alive only during playback started by this addon."""
import time
import threading

import xbmc
import xbmcaddon
import xbmcgui
import xbmcvfs

from resources.lib.api import Client, OdidoError
from resources.lib.relay import PROPERTY as RELAY_PROPERTY, Server

PROPERTY = 'plugin.video.odidotv.manifest'


def is_our_playback(playing, filename, manifest):
    return bool(playing and manifest and (filename.split('|', 1)[0] == manifest or
                                         filename.startswith('plugin://plugin.video.odidotv/')))


def run():
    monitor, player = xbmc.Monitor(), xbmc.Player()
    window = xbmcgui.Window(10000)
    profile = xbmcvfs.translatePath(xbmcaddon.Addon().getAddonInfo('profile'))
    window.clearProperty(RELAY_PROPERTY)
    def report(code):
        window.setProperty('plugin.video.odidotv.last_playback_error', code)
        xbmc.log('[plugin.video.odidotv] ' + code, xbmc.LOGWARNING)
    server = Server(profile, report)
    worker = threading.Thread(target=server.serve_forever, daemon=True)
    worker.start()
    window.setProperty(RELAY_PROPERTY, server.base)
    last = 0
    try:
        while not monitor.abortRequested():
            try:
                manifest = window.getProperty(PROPERTY)
                playing = player.isPlayingVideo()
                filename = player.getPlayingFile() if playing else ''
                if is_our_playback(playing, filename, manifest):
                    if time.monotonic() - last >= 60:
                        client = Client(profile)
                        if client.logged_in:
                            client.heartbeat()
                        last = time.monotonic()
                else:
                    last = 0
            except OdidoError:
                last = time.monotonic()
                xbmc.log('[plugin.video.odidotv] HEARTBEAT_FAILED', xbmc.LOGWARNING)
            except Exception:
                last = time.monotonic()
                xbmc.log('[plugin.video.odidotv] SERVICE_ERROR', xbmc.LOGWARNING)
            if monitor.waitForAbort(5):
                break
    finally:
        window.clearProperty(RELAY_PROPERTY)
        window.clearProperty(PROPERTY)
        server.shutdown()
        server.server_close()
        worker.join(timeout=2)


if __name__ == '__main__':
    run()
