"""IPTV Manager JSON-STREAMS / JSON-EPG v1, with no playback secrets exported."""
import datetime as dt
import json
import os
import socket
import time
from urllib.parse import urlencode

from .api import AuthError, OdidoError
from .storage import read_json, write_json
from .tvtime import day_bounds, local_time

BASE = 'plugin://plugin.video.odidotv/'


def selection(value):
    if not value:
        return None  # All channels; [] explicitly means no channels.
    try:
        result = json.loads(value)
    except ValueError:
        raise OdidoError('IPTV_INVALID_SELECTION') from None
    if not isinstance(result, list) or any(not isinstance(item, str) or not item.isdigit() for item in result):
        raise OdidoError('IPTV_INVALID_SELECTION')
    return set(result)


def playback_url(kind, identifier, channel='', title='', **params):
    return BASE + '?' + urlencode({'action': 'play', 'kind': kind, 'id': str(identifier),
                                  'channel': str(channel), 'title': title, **params})


def channel_key(identifier):
    return 'odido.' + str(identifier)


def programme(row, replay, now):
    if not row.get('id') or not isinstance(row.get('title'), str):
        return None
    start, end = row.get('start', 0), row.get('end', 0)
    if not isinstance(start, (int, float)) or not isinstance(end, (int, float)) or start <= 0 or end <= start:
        return None
    try:
        result = {'start': dt.datetime.fromtimestamp(start / 1000, dt.timezone.utc).isoformat(),
                  'stop': dt.datetime.fromtimestamp(end / 1000, dt.timezone.utc).isoformat(),
                  'title': row['title'], 'description': row.get('plot', ''), 'image': row.get('image', '')}
    except (ValueError, OverflowError, OSError):
        return None
    if replay or now * 1000 < end:
        # Keep the programme identity/times: a link exported while live must
        # become replay after it finishes, rather than tune a different show.
        # Future entries also need timed links so they work when they become
        # live without requiring a fresh guide import at every show boundary.
        result['stream'] = playback_url('program', row['id'], row['channel'], row['title'],
                                       programme_start=int(start), programme_end=int(end),
                                       replay='1' if replay else '0')
    return result


class Exporter:
    def __init__(self, client, selected=None, clock=time.time, cancelled=lambda: False, refresh_channels=False):
        self.client, self.clock, self.cancelled = client, clock, cancelled
        client.require_session()
        rows = client.channel_rows(refresh=True) if refresh_channels else client.channel_rows()
        self.rows = [row for row in rows if selected is None or str(row['ID']) in selected]
        self.errors = []

    def channels(self):
        streams = []
        for row in self.rows:
            identifier = str(row['ID'])
            stream = {'id': channel_key(identifier), 'name': row['name'],
                      'stream': playback_url('channel', identifier, title=row['name']),
                      'logo': row.get('logo') or 'icon.png', 'group': ['Odido TV']}
            number = str(row.get('channelno', ''))
            if number.isdigit() and int(number) > 0:
                stream['preset'] = int(number)
            streams.append(stream)
        return {'version': 1, 'streams': streams}

    def _query(self, identifiers, start, end):
        self.failed = set()
        try:
            return self.client.epg(identifiers, start, end, count=300)
        except AuthError:
            raise
        except OdidoError as error:
            if not str(error).startswith('API_') or len(identifiers) == 1:
                raise
            rows = []
            for identifier in identifiers:
                if self.cancelled():
                    raise OdidoError('IPTV_CANCELLED')
                try:
                    rows.extend(self.client.epg([identifier], start, end, count=300))
                except AuthError:
                    raise
                except OdidoError as single_error:
                    self.failed.add(identifier)
                    self.errors.append(str(single_error))
                    if not str(single_error).startswith('API_'):
                        raise
            return rows

    def epg(self, days=7, force=False):
        if days not in (1, 3, 7):
            raise OdidoError('IPTV_INVALID_DAYS')
        now = self.clock()
        today = local_time(now).date()
        # Prioritize today's guide, then tomorrow, then the replay history.
        dates = [today, today + dt.timedelta(days=1)] + [today - dt.timedelta(days=n) for n in range(1, days)]
        directory = os.path.join(self.client.profile, 'iptv_epg')
        os.makedirs(directory, exist_ok=True)
        valid_files = {date.strftime('%Y%m%d') + '.json' for date in dates}
        for name in os.listdir(directory):
            if len(name) == 13 and name[:8].isascii() and name[:8].isdigit() and name.endswith('.json') and name not in valid_files:
                os.unlink(os.path.join(directory, name))
        identifiers = [str(row['ID']) for row in self.rows]
        output = {channel_key(identifier): [] for identifier in identifiers}
        seen = set()
        stop_fetching = False
        for date in dates:
            if self.cancelled():
                raise OdidoError('IPTV_CANCELLED')
            day = date.strftime('%Y%m%d')
            start, end = day_bounds(day)
            path = os.path.join(directory, day + '.json')
            cached = read_json(path, {})
            cached = cached if isinstance(cached, dict) else {}
            # Keep cache bounded to channels in the current catalogue/selection.
            cached = {key: value for key, value in cached.items() if key in identifiers
                      and isinstance(value, dict) and isinstance(value.get('rows'), list)}
            ttl = 86400 if date < today else 900 if date == today else 3600
            missing = []
            for identifier in identifiers:
                entry = cached.get(identifier, {})
                stamp = entry.get('updated', 0)
                if force or not isinstance(stamp, (int, float)) or not 0 <= now - stamp < ttl or not isinstance(entry.get('rows'), list):
                    missing.append(identifier)
            for offset in range(0, len(missing), 20):
                if stop_fetching:
                    break
                if self.cancelled():
                    raise OdidoError('IPTV_CANCELLED')
                batch = missing[offset:offset + 20]
                try:
                    fetched = self._query(batch, start, end)
                except AuthError:
                    raise
                except OdidoError as error:
                    self.errors.append(str(error))
                    # Retain a stale schedule for the requested day if available.
                    if not str(error).startswith('API_'):
                        stop_fetching = True
                    continue
                for identifier in batch:
                    if identifier not in self.failed:
                        cached[identifier] = {'updated': now, 'rows': [row for row in fetched if row.get('channel') == identifier]}
            write_json(path, cached)
            for channel in self.rows:
                identifier = str(channel['ID'])
                for row in cached.get(identifier, {}).get('rows', []):
                    if not isinstance(row, dict) or row.get('channel') != identifier:
                        continue
                    key = (identifier, row.get('id'), row.get('start'))
                    item = programme(row, channel.get('replay', True), now)
                    if item is not None and key not in seen:
                        output[channel_key(identifier)].append(item)
                        seen.add(key)
        for rows in output.values():
            rows.sort(key=lambda row: row['start'])
        return {'version': 1, 'epg': output}


def send(port, kind, producer, report, connect=socket.create_connection):
    """Connect immediately: Manager allows only ten seconds for the handshake.

    It waits without a timeout after accepting, so slow first EPG imports can
    complete. sendall handles responses larger than a socket's first write.
    """
    try:
        port = int(port)
    except (TypeError, ValueError):
        raise OdidoError('IPTV_INVALID_PORT') from None
    if not 1024 <= port <= 65535 or kind not in ('channels', 'epg'):
        raise OdidoError('IPTV_INVALID_CALLBACK')
    with connect(('127.0.0.1', port), timeout=5) as connection:
        connection.settimeout(30)
        try:
            payload = producer()
        except Exception as error:
            report(error)
            payload = {'version': 1, 'streams': []} if kind == 'channels' else {'version': 1, 'epg': {}}
        # Manager decodes each received chunk separately. ASCII JSON escapes
        # prevent a split multibyte title (for example, é) breaking its decoder.
        connection.sendall(json.dumps(payload, ensure_ascii=True).encode('ascii'))
