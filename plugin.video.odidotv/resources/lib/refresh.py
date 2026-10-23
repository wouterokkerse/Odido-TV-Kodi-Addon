"""Scope Manager's paired callbacks without discarding the unchanged export."""
import os
import secrets
import time

from .api import OdidoError
from .storage import read_json, write_json

TIMEOUT = 1800


def payload_path(profile, kind):
    return os.path.join(profile, 'iptv_payload_' + kind + '.json')


def cached(profile, kind):
    value = read_json(payload_path(profile, kind), {})
    payload = value.get('payload') if isinstance(value, dict) else None
    key = 'streams' if kind == 'channels' else 'epg'
    expected = list if kind == 'channels' else dict
    return value if (isinstance(payload, dict) and payload.get('version') == 1 and
                     isinstance(payload.get(key), expected)) else None


def pending(profile, now=None):
    value = read_json(os.path.join(profile, 'iptv_refresh.json'), {})
    now = time.time() if now is None else now
    if not isinstance(value, dict) or value.get('mode') not in ('both', 'channels', 'epg'):
        return {}
    stamp = value.get('requested', 0)
    if not isinstance(stamp, (int, float)) or not 0 <= now - stamp < TIMEOUT:
        return {}
    return value


def request(profile, manager, mode='both', force=False, now=None):
    if mode not in ('both', 'channels', 'epg'):
        raise ValueError('Invalid refresh mode')
    now = time.time() if now is None else now
    if pending(profile, now):
        raise OdidoError('IPTV_REFRESH_BUSY')
    for kind in ('channels', 'epg'):
        status = read_json(os.path.join(profile, 'iptv_export_' + kind + '.json'), {})
        if isinstance(status, dict):
            stamp = status.get('updated', 0)
            if (status.get('phase') in ('started', 'ready') and
                    isinstance(stamp, (int, float)) and 0 <= now - stamp < TIMEOUT):
                raise OdidoError('IPTV_REFRESH_BUSY')
    if mode != 'both' and not cached(profile, 'epg' if mode == 'channels' else 'channels'):
        raise OdidoError('IPTV_REFRESH_BASELINE_REQUIRED')
    value = {'id': secrets.token_hex(16), 'mode': mode, 'force': force, 'requested': now}
    write_json(os.path.join(profile, 'iptv_refresh.json'), value)
    try:
        # Manager's service polls this timestamp every 30s. The manual refresh
        # script opens progress/settings dialogs and cannot select just one part.
        manager.setSetting('last_refreshed', '0')
    except Exception:
        complete(profile, value)
        raise


def complete(profile, value):
    path = os.path.join(profile, 'iptv_refresh.json')
    current = read_json(path, {})
    if value.get('id') and isinstance(current, dict) and current.get('id') == value['id']:
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass
