"""Request silent guide imports through IPTV Manager's existing service."""
import os
import time

from .storage import read_json
from .refresh import pending, request

MANAGER = 'service.iptv.manager'
INTERVAL = 3600
RETRY = 900
BUSY_TIMEOUT = 1800


class GuideRefresh:
    def __init__(self, profile, addon, get_addon, enabled, clock=time.time,
                 monotonic=time.monotonic):
        self.profile, self.addon = profile, addon
        self.get_addon, self.enabled = get_addon, enabled
        self.clock, self.monotonic = clock, monotonic
        # Let Kodi and Manager finish starting before requesting an import.
        self.next_check = monotonic() + 60

    def tick(self):
        now_mono = self.monotonic()
        if now_mono < self.next_check:
            return
        self.next_check = now_mono + 30
        if (self.addon.getSetting('iptv.enabled') != 'true' or
                self.addon.getSetting('iptv.auto_refresh') == 'false' or
                not self.enabled(MANAGER) or not self.enabled('pvr.iptvsimple')):
            return
        state = read_json(os.path.join(self.profile, 'session.json'), {})
        if not isinstance(state, dict) or not (
                (state.get('logged_in') and state.get('csrf_token')) or state.get('credentials')):
            return
        now = self.clock()
        if pending(self.profile, now):
            return
        for kind in ('channels', 'epg'):
            status = read_json(os.path.join(self.profile, 'iptv_export_' + kind + '.json'), {})
            if not isinstance(status, dict):
                continue
            stamp = status.get('updated', 0)
            age = now - stamp if isinstance(stamp, (int, float)) else float('inf')
            # Do not overlap a manual import or Manager's own scheduled import.
            if status.get('phase') in ('started', 'ready') and 0 <= age < BUSY_TIMEOUT:
                return
            fetched = status.get('fetched', stamp)
            if (kind == 'epg' and status.get('phase') == 'sent' and
                    not status.get('error') and isinstance(fetched, (int, float)) and
                    0 <= now - fetched < INTERVAL):
                return
        # Use Manager's silent service path. Its refresh script opens settings
        # and progress dialogs. The service checks this timestamp every 30s,
        # writes the combined M3U/XMLTV, and defers PVR restart during TV playback.
        # Preserve the user's Manager interval and all other source settings.
        self.next_check = now_mono + RETRY
        manager = self.get_addon(MANAGER)
        request(self.profile, manager, now=now)
