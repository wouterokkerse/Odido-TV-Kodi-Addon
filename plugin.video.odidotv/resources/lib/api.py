"""Odido VSP client. Production compatibility still needs subscriber validation.

Uses the public T-Mobile client protocol on the current Odido TV origin.
See SOURCES.md for confirmed contracts and remaining assumptions.
"""
import http.cookiejar
import json
import os
import secrets
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlparse
from urllib.request import HTTPCookieProcessor, Request, build_opener

from .storage import read_json, write_json
from .catalog import load_channels
from .tvtime import day_bounds

ORIGIN = 'https://tv.odido.nl'
USER_AGENT = ('Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
              'AppleWebKit/537.36 (KHTML, like Gecko) '
              'Chrome/130.0.0.0 Safari/537.36')
HEADERS = {'User-Agent': USER_AGENT, 'Origin': ORIGIN, 'Referer': ORIGIN + '/',
           'Accept': 'application/json', 'Content-Type': 'application/json'}
DEFAULT_DEVICE_NAME = 'Kodi Odido TV'


class OdidoError(Exception):
    """Only safe, bounded error identifiers, never provider messages."""


class AuthError(OdidoError):
    pass


def safe_code(value):
    value = str(value)
    return value if value.isalnum() and len(value) < 40 else 'UNKNOWN'


def normalize_device_name(value):
    # Keep a short readable label; strip control characters and whitespace.
    if not isinstance(value, str):
        return DEFAULT_DEVICE_NAME
    value = ' '.join(''.join(c if c.isprintable() else ' ' for c in value).split())
    return value[:64] or DEFAULT_DEVICE_NAME


def media_id(row):
    files = row.get('physicalChannels', row.get('mediaFiles', []))
    # Odido's current channel/media discovery schema must be subscriber-tested.
    # Prefer explicitly DASH media, preserve provider order when unspecified.
    files = sorted(files, key=lambda item: 'dash' in str(item.get('format', '')).lower(), reverse=True)
    for media in files:
        identifier = media.get('mediaID', media.get('ID'))
        if identifier is not None:
            return str(identifier)
    raise OdidoError('NO_MEDIA_ID')


def record(row, kind, channel=''):
    identifier = row.get('ID')
    if identifier is None:
        raise OdidoError('MISSING_CONTENT_ID')
    picture = row.get('picture')
    posters = picture.get('posters') if isinstance(picture, dict) else []
    posters = posters if isinstance(posters, list) else []
    image = posters[0] if posters and isinstance(posters[0], str) else ''
    if image and urlparse(image).scheme != 'https':
        image = ''
    def timestamp(key):
        try:
            return int(row.get(key) or 0)
        except (TypeError, ValueError, OverflowError):
            return 0
    start, end = timestamp('startTime'), timestamp('endTime')
    plot = row.get('introduce')
    return {'id': str(identifier), 'kind': kind,
            'channel': str(channel or row.get('channelID', '')),
            'title': str(row.get('name', identifier)),
            'plot': plot if isinstance(plot, str) else '', 'image': image,
            'start': start, 'end': end,
            'duration': max(0, (end - start) // 1000)}


def playback(value):
    url = value.get('playURL', '')
    if not isinstance(url, str) or urlparse(url).scheme != 'https':
        raise OdidoError('NO_HTTPS_MANIFEST')
    authorization = value.get('authorizeResult') or {}
    triggers = authorization.get('triggers', [])
    license_url, custom_data = '', ''
    for trigger in triggers:
        candidate = trigger.get('licenseURL', '')
        if candidate:
            if urlparse(candidate).scheme != 'https':
                raise OdidoError('INVALID_LICENSE_URL')
            license_url = candidate
            custom_data = trigger.get('customData', '')
            break
    # No trigger is allowed for clear DASH channels. InputStream Adaptive will
    # reject encrypted manifests without a license; no decryption fallback.
    return {'url': url, 'license': license_url, 'custom_data': custom_data}


class Client:
    def __init__(self, profile, transport=None, device_name=None, catalog_loader=None):
        self.profile = profile
        os.makedirs(profile, exist_ok=True)
        self.state_path = os.path.join(profile, 'session.json')
        self.cookie_path = os.path.join(profile, 'cookies.txt')
        self.state = read_json(self.state_path, {})
        if not self.state.get('device_id'):
            self.state = {'device_id': ''.join(str(secrets.randbelow(10)) for _ in range(10)),
                          'logged_in': False, 'csrf_token': ''}
        self.device_name = normalize_device_name(
            self.state.get('device_name', DEFAULT_DEVICE_NAME) if device_name is None else device_name)
        self.generation = self.state.get('generation')
        self.jar = http.cookiejar.MozillaCookieJar(self.cookie_path)
        if self.state.get('logged_in'):
            try:
                self.jar.load(ignore_discard=True)
            except (OSError, http.cookiejar.LoadError):
                self.state['logged_in'] = False
        self.opener = build_opener(HTTPCookieProcessor(self.jar))
        self.transport = transport or self._http
        self.catalog_loader = catalog_loader or load_channels

    @property
    def logged_in(self):
        return bool(self.state.get('logged_in') and self.state.get('csrf_token'))

    def _save(self):
        # A background request may complete after a foreground sign-out/login.
        # Do not restore that old session over a newer session generation.
        current = read_json(self.state_path, {})
        if current.get('generation') != self.generation:
            raise AuthError('SESSION_CHANGED')
        write_json(self.state_path, self.state)
        self.generation = self.state.get('generation')
        self.jar.save(ignore_discard=True)
        os.chmod(self.cookie_path, 0o600)

    def logout(self):
        # Local sign-out. Device registration remains managed by Odido.
        self.jar.clear()
        self.state.update(logged_in=False, csrf_token='', generation=secrets.token_hex(16))
        self._save()

    def _http(self, method, payload, params):
        url = ORIGIN + '/VSP/V3/' + method + '?' + urlencode(params)
        headers = dict(HEADERS)
        if self.state.get('csrf_token'):
            headers['X_CSRFToken'] = self.state['csrf_token']
        request = Request(url, data=json.dumps(payload).encode('utf-8'), headers=headers)
        try:
            with self.opener.open(request, timeout=30) as response:
                raw = response.read(8 * 1024 * 1024 + 1)
            if len(raw) > 8 * 1024 * 1024:
                raise OdidoError('RESPONSE_TOO_LARGE')
            value = json.loads(raw.decode('utf-8'))
            if isinstance(value, str):
                value = json.loads(value)
            self._save()
            return value
        except HTTPError as error:
            if error.code in (401, 403):
                raise AuthError('HTTP_%d' % error.code) from None
            raise OdidoError('HTTP_%d' % error.code) from None
        except (URLError, OSError, TimeoutError):
            raise OdidoError('NETWORK_ERROR') from None
        except (ValueError, UnicodeError):
            raise OdidoError('INVALID_JSON') from None

    def request(self, method, payload=None, params=None):
        if not method.isalnum():
            raise ValueError('Invalid API method')
        try:
            value = self.transport(method, payload or {}, params or {'from': 'throughMSAAccess'})
            if not isinstance(value, dict) or not isinstance(value.get('result'), dict):
                raise OdidoError('INVALID_RESPONSE')
            code = safe_code(value['result'].get('retCode', 'UNKNOWN'))
            if code != '000000000':
                if code == '157022007':
                    raise OdidoError('DEVICE_LIMIT')
                # No undocumented numeric codes are silently labelled expired.
                stage = {'PlayChannel': '_PLAYCHANNEL',
                         'QueryPlaybill': '_PROGRAMME',
                         'QueryPlaybillListStcProps': '_GUIDE',
                         'QueryAllChannel': '_CHANNELS'}.get(method, '')
                raise OdidoError('API_' + code + stage)
            if value.get('csrfToken'):
                self.state['csrf_token'] = value['csrfToken']
                self._save()
            return value
        except AuthError:
            self.logout()
            raise

    def login(self, username, pin):
        # Persist the label even if registration fails. Changing the label must
        # never generate another identity or consume another registration slot.
        self.state['device_name'] = self.device_name
        self.logout()
        device = self.state['device_id']
        payload = {
            'authenticateBasic': {
                'VUID': '6_7_' + device, 'clientPasswd': pin,
                'isSupportWebpImgFormat': '0', 'lang': 'nl',
                'needPosterTypes': [str(n) for n in range(1, 8)],
                'timeZone': 'Europe/Amsterdam', 'userID': username, 'userType': '0'},
            'authenticateDevice': {
                'CADeviceInfos': [{'CADeviceID': device, 'CADeviceType': '7'}],
                # Requested friendly name; current Odido acceptance still needs
                # live verification. deviceModel remains the protocol identifier.
                'deviceName': self.device_name,
                'deviceModel': '3103_PCClient', 'physicalDeviceID': device, 'terminalID': device},
            'authenticateTolerant': {
                'areaCode': '', 'bossID': '', 'subnetID': '', 'templateName': '', 'userGroup': ''}}
        try:
            value = self.request('Authenticate', payload)
            if not value.get('csrfToken'):
                raise OdidoError('NO_CSRF_TOKEN')
            self.state.update(logged_in=True, csrf_token=value['csrfToken'])
            self._save()
        except OdidoError:
            self.logout()
            raise

    def require_session(self):
        if not self.logged_in:
            raise AuthError('LOGIN_REQUIRED')

    def heartbeat(self):
        self.require_session()
        try:
            return self.request('OnLineHeartbeat', params={'from': 'inMSAAccess'})
        except OdidoError as error:
            if str(error).startswith('API_'):
                self.logout()
                raise AuthError('SESSION_REJECTED') from None
            # A network failure must not discard a potentially valid session.
            raise

    def channel_rows(self):
        self.require_session()
        # Match the working reference's explicit OTT channel/media pairs.
        # QueryAllChannel was an unverified cross-provider discovery assumption.
        try:
            return self.catalog_loader(self.profile)
        except (OSError, ValueError):
            raise OdidoError('CHANNEL_CATALOG_UNAVAILABLE') from None

    def channels(self):
        return [record(row, 'channel') for row in self.channel_rows()]

    def epg(self, channel_ids, start, end, count=100, paginate=True):
        self.require_session()
        result, seen = [], set()
        for page in range(100):
            value = self.request('QueryPlaybillListStcProps', {
                'needChannel': '0',
                'queryChannel': {'channelIDs': list(map(str, channel_ids)), 'isReturnAllMedia': '1'},
                'queryPlaybill': {'count': str(count), 'endTime': end, 'isFillProgram': '1',
                                 'offset': str(page * count), 'startTime': start, 'type': '0'}},
                {'SID': 'queryPlaybillListStcProps3', 'DEVICE': 'PC',
                 'DID': self.state['device_id'], 'from': 'throughMSAAccess'})
            groups = value.get('channelPlaybills')
            if not isinstance(groups, list):
                raise OdidoError('GUIDE_SCHEMA_CHANGED')
            added, full = 0, False
            for group in groups:
                channel = group.get('channelID', channel_ids[0] if len(channel_ids) == 1 else '')
                rows = group.get('playbillLites', [])
                full = full or len(rows) >= count
                for row in rows:
                    item = record(row, 'program', channel)
                    key = (item['channel'], item['id'])
                    if key not in seen:
                        seen.add(key)
                        result.append(item)
                        added += 1
            if not full or not paginate:
                return result
            if not added:
                raise OdidoError('PAGINATION_STALLED')
        raise OdidoError('PAGINATION_LIMIT')

    def day(self, channel, day):
        start, end = day_bounds(day)
        # Match the reference replay query; live now() remains count=1.
        return self.epg([channel], start, end, count=300)

    def now(self, channel_ids):
        import time
        now = int(time.time() * 1000)
        return self.epg(channel_ids, now, now, count=1, paginate=False) if channel_ids else []

    def live_programmes(self, channel_ids):
        """Bound menu requests; retain other channels when one is unavailable.

        Stream startup still uses the original single-channel now() request.
        """
        rows, errors = [], []
        channel_ids = list(dict.fromkeys(map(str, channel_ids)))
        for offset in range(0, len(channel_ids), 20):
            batch = channel_ids[offset:offset + 20]
            try:
                rows.extend(self.now(batch))
            except AuthError:
                raise
            except OdidoError as error:
                if not str(error).startswith('API_'):
                    # A broken connection/schema will not improve by issuing
                    # hundreds of individual requests against the same service.
                    errors.append(str(error))
                    break
                if len(batch) == 1:
                    errors.append(str(error))
                    continue
                # Use the known-working live-startup request for a rejected
                # group; no unverified media identifiers or alternative APIs.
                for channel in batch:
                    try:
                        rows.extend(self.now([channel]))
                    except AuthError:
                        raise
                    except OdidoError as single_error:
                        errors.append(str(single_error))
                        if not str(single_error).startswith('API_'):
                            return rows, list(dict.fromkeys(errors))
        return rows, list(dict.fromkeys(errors))

    def stream(self, kind, identifier, channel=''):
        self.require_session()
        self.heartbeat()
        if kind == 'channel':
            channel = str(identifier)
            # The user's working dut-iptv fork opens live channels through CUTV
            # with the current playbill, rather than a programme-less BTV call.
            current = next((item for item in self.now([channel])
                            if item['channel'] == channel), None)
            if current is None:
                raise OdidoError('NO_CURRENT_PROGRAMME')
            identifier = current['id']
        elif kind == 'program':
            value = self.request('QueryPlaybill', {'playbillID': identifier,
                        'channelNamespace': '310303', 'isReturnAllMedia': '1'})
            detail = value.get('playbillDetail', {})
            channel = channel or str(detail.get('channelID', ''))
        else:
            raise OdidoError('INVALID_PLAYBACK_TYPE')
        row = next((r for r in self.channel_rows() if str(r.get('ID')) == channel), None)
        if row is None:
            raise OdidoError('CHANNEL_UNAVAILABLE')
        payload = {'businessType': 'CUTV',
                   'channelID': channel, 'checkLock': {'checkType': '0'},
                   'isHTTPS': '1', 'isReturnProduct': '1', 'mediaID': media_id(row),
                   'playbillID': identifier}
        # Only PlayChannel: never subscribe, rent, purchase or alter devices.
        return playback(self.request('PlayChannel', payload))

    def media_headers(self, url, license_request=False, custom_data=''):
        request = Request(url, headers={'User-Agent': USER_AGENT, 'Origin': ORIGIN, 'Referer': ORIGIN + '/'})
        self.jar.add_cookie_header(request)
        headers = dict(request.header_items())
        if license_request:
            headers['Content-Type'] = 'application/octet-stream'
            if urlparse(url).hostname == urlparse(ORIGIN).hostname:
                headers['X_CSRFToken'] = self.state.get('csrf_token', '')
            if custom_data:
                headers['AcquireLicense.CustomData'] = custom_data
                headers['CADeviceType'] = 'Widevine OTT client'
        return headers
