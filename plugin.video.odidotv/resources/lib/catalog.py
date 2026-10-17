"""The same public OTT channel/media catalogue used by dut-iptv's Odido client."""
import json
import os
import time
from urllib.request import Request, urlopen
from urllib.parse import urlparse

from .storage import read_json, write_json

URL = 'https://dut-epg.github.io/tmobile/channels.json'
SNAPSHOT = os.path.join(os.path.dirname(os.path.dirname(__file__)), 'channels.json')


def validate(value):
    if not isinstance(value, dict) or not 1 <= len(value) <= 2000:
        raise ValueError('Invalid channel catalogue')
    rows = []
    for key, item in value.items():
        if not isinstance(item, dict):
            raise ValueError('Invalid channel entry')
        channel, media = str(item.get('id', '')), str(item.get('assetid', ''))
        if channel != key or not channel.isascii() or not channel.isdigit() or not media.isascii() or not media.isdigit():
            raise ValueError('Invalid channel/media pair')
        if not isinstance(item.get('name'), str) or not item['name'].strip():
            raise ValueError('Invalid channel name')
        number = str(item.get('channelno', ''))
        logo = item.get('icon', '')
        logo = logo if isinstance(logo, str) and urlparse(logo).scheme == 'https' else ''
        rows.append({'ID': channel, 'name': item['name'], 'channelno': number,
                     'logo': logo, 'replay': str(item.get('replay', '1')) == '1',
                     'physicalChannels': [{'mediaID': media}]})
    return sorted(rows, key=lambda row: (int(row['channelno']) if row['channelno'].isdigit() else 10000, row['name']))


def download():
    # Separate opener: never send the Odido session, CSRF or PIN to the feed.
    with urlopen(Request(URL, headers={'Accept': 'application/json'}), timeout=10) as response:
        raw = response.read(1024 * 1024 + 1)
    if len(raw) > 1024 * 1024:
        raise ValueError('Channel catalogue too large')
    return json.loads(raw.decode('utf-8'))


def load_channels(profile, fetch=download):
    path = os.path.join(profile, 'channel_catalog.json')
    cached = read_json(path, {})
    if not isinstance(cached, dict):
        cached = {}
    try:
        rows = validate(cached.get('channels'))
    except ValueError:
        rows = None
    timestamp = cached.get('updated', 0)
    if rows and isinstance(timestamp, (int, float)) and 0 <= time.time() - timestamp < 86400:
        return rows
    try:
        value = fetch()
        fresh = validate(value)
        write_json(path, {'updated': time.time(), 'channels': value})
        return fresh
    except (OSError, ValueError):
        # An unavailable public feed must not prevent use of the known mapping.
        return rows if rows is not None else validate(read_json(SNAPSHOT))
