"""Per-playback, threaded loopback media relay.

Adapted behavior from wouterokkerse/dut-iptv: discover Odido's final redirected
media base, retain its /wh... prefix, stream segments, and isolate license headers.
No account responses, signed URLs or license payloads are written to disk.
"""
import base64
import copy
import gzip
import html
import http.cookiejar
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import re
import secrets
import threading
import time
from urllib.error import HTTPError
from urllib.parse import parse_qsl, quote, urljoin, urlsplit, urlunsplit
from urllib.request import HTTPRedirectHandler, HTTPCookieProcessor, ProxyHandler, Request, build_opener
import uuid
from xml.dom.minidom import parseString

from .api import ORIGIN, USER_AGENT

MAX_MANIFEST = 8 * 1024 * 1024
MAX_LICENSE = 4 * 1024 * 1024
PROPERTY = 'plugin.video.odidotv.relay'


class RelayError(Exception):
    pass


def require_https(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password:
        raise RelayError('INVALID_UPSTREAM_URL')
    return url


class ScopedRedirects(HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        require_https(new_url)
        redirected = super().redirect_request(request, response, code, message, headers, new_url)
        if redirected and urlsplit(request.full_url).netloc != urlsplit(new_url).netloc:
            for key in list(redirected.headers):
                if key.lower() in ('cookie', 'authorization', 'x_csrftoken',
                                   'acquirelicense.customdata', 'cadevicetype', 'host'):
                    del redirected.headers[key]
        return redirected


class Transport:
    def __init__(self, client):
        # CookieJar locks cookie extraction/header operations internally. Sharing
        # it retains scoped CDN cookies set by a redirect for later segments.
        self.jar = http.cookiejar.CookieJar()
        for cookie in client.jar:
            self.jar.set_cookie(copy.copy(cookie))
        self.csrf = client.state.get('csrf_token', '')

    def open(self, url, data=None, license_request=False, custom_data='', headers=None):
        require_https(url)
        outbound = {'User-Agent': USER_AGENT, 'Origin': ORIGIN, 'Referer': ORIGIN + '/',
                    'Accept': '*/*', 'Accept-Encoding': 'identity'}
        for key, value in (headers or {}).items():
            if key.lower() in ('range', 'if-range', 'if-none-match', 'if-modified-since'):
                outbound[key] = value
        if license_request:
            outbound['Content-Type'] = 'application/octet-stream'
            if urlsplit(url).hostname == urlsplit(ORIGIN).hostname:
                outbound['X_CSRFToken'] = self.csrf
            if custom_data:
                outbound['AcquireLicense.CustomData'] = custom_data
                outbound['CADeviceType'] = 'Widevine OTT client'
        # A fresh opener per request avoids shared Session state between threads.
        opener = build_opener(ScopedRedirects(), HTTPCookieProcessor(self.jar))
        request = Request(url, data=data, headers=outbound)
        try:
            return opener.open(request, timeout=30)
        except HTTPError as response:
            return response


def browser_mpd_url(url, xml):
    """Append missing browser routing parameters, preserving signed query bytes."""
    values = {}
    text = html.unescape(xml)
    for key in ('service_devid', 'mag_hms', 'online'):
        match = re.search(r'\b' + key + r'=([^&"\s<>]+)', text)
        if not match:
            return url
        values[key] = match.group(1)
    query = dict(parse_qsl(urlsplit(url).query, keep_blank_values=True))
    if all(query.get(key) for key in ('hms_devid', 'mag_hms', 'RTS', 'from')):
        return url
    additions = {'hms_devid': values['service_devid'], 'mag_hms': values['mag_hms'],
                 'online': values['online'], 'RTS': values['online'],
                 'from': '14', '_': str(int(time.time() * 1000))}
    match = re.search(r'/PLTV/([^/]+)/', urlsplit(url).path)
    if match:
        additions['icpid'] = match.group(1)
    extra = '&'.join(quote(key) + '=' + quote(value, safe='')
                     for key, value in additions.items() if not query.get(key))
    if not extra:
        return url
    parts = urlsplit(url)
    return urlunsplit(parts._replace(query=parts.query + ('&' if parts.query else '') + extra))


def normalize_manifest(xml):
    if '<!DOCTYPE' in xml.upper() or '<!ENTITY' in xml.upper():
        raise RelayError('INVALID_MANIFEST_XML')
    return xml.replace('_xmlns:cenc', 'xmlns:cenc').replace('_:default_KID', 'cenc:default_KID')


def inject_default_kids(document):
    """Copy the public KID identifier from PlayReady metadata if cenc omits it.

    This does not obtain keys or decrypt media; Widevine still licenses playback.
    Preserve all PSSH, representations, periods and timeline nodes.
    """
    for adaptation in document.getElementsByTagNameNS('*', 'AdaptationSet'):
        protections = adaptation.getElementsByTagNameNS('*', 'ContentProtection')
        if any(p.getAttribute('cenc:default_KID') or p.getAttribute('default_KID') for p in protections):
            continue
        identifier = None
        for protection in protections:
            for pro in protection.getElementsByTagNameNS('*', 'pro'):
                try:
                    encoded = ''.join(n.data for n in pro.childNodes if n.nodeType == n.TEXT_NODE)
                    header = base64.b64decode(encoded).decode('utf-16-le', errors='ignore')
                    match = re.search(r'<KID\b[^>]*\bVALUE=["\']([^"\']+)', header, re.I)
                    match = match or re.search(r'<KID>([^<]+)</KID>', header, re.I)
                    if match:
                        raw = base64.b64decode(match.group(1))
                        if len(raw) == 16:
                            identifier = str(uuid.UUID(bytes_le=raw))
                except (ValueError, UnicodeError):
                    pass
        if identifier:
            target = next((p for p in protections if p.getAttribute('schemeIdUri') ==
                           'urn:mpeg:dash:mp4protection:2011'), None)
            if target is not None:
                document.documentElement.setAttribute('xmlns:cenc', 'urn:mpeg:cenc:2013')
                target.setAttribute('cenc:default_KID', identifier)


def normalize_metadata(document):
    for node in list(document.getElementsByTagName('pssh')):
        if node.namespaceURI != 'urn:mpeg:cenc:2013':
            document.documentElement.setAttribute('xmlns:cenc', 'urn:mpeg:cenc:2013')
            corrected = document.createElementNS('urn:mpeg:cenc:2013', 'cenc:pssh')
            for key in node.attributes.keys():
                corrected.setAttribute(key, node.getAttribute(key))
            while node.firstChild:
                corrected.appendChild(node.firstChild)
            node.parentNode.replaceChild(corrected, node)
    for node in document.getElementsByTagNameNS('*', 'AudioChannelConfiguration'):
        if node.getAttribute('schemeIdUri') == 'tag:dolby.com,2014:dash:audio_channel_configuration:2011':
            node.setAttribute('schemeIdUri', 'urn:dolby:dash:audio_channel_configuration:2011')


class Playback:
    def __init__(self, stream, transport):
        self.manifest_url = require_https(stream['url'])
        self.license_url = require_https(stream['license']) if stream.get('license') else ''
        self.custom_data = stream.get('custom_data', '')
        self.transport = transport
        self.media_prefix = ''
        self.origins = {urlsplit(self.manifest_url).netloc}
        self.bases = {}
        self.base_ids = {}
        self.lock = threading.Lock()
        self.last_used = time.monotonic()

    def set_final_url(self, url):
        require_https(url)
        parts = urlsplit(url)
        with self.lock:
            self.origins.add(parts.netloc)
            for marker in ('/PLTV/', '/TVOD/'):
                if marker in parts.path:
                    self.media_prefix = urlunsplit((parts.scheme, parts.netloc,
                                                   parts.path.split(marker, 1)[0] + '/', '', ''))
                    break

    def resolve(self, value, base):
        resolved = urljoin(base, value)
        parts = urlsplit(resolved)
        with self.lock:
            prefix, origins = self.media_prefix, set(self.origins)
        if prefix and parts.netloc in origins:
            # Root/PLTV-relative media paths must retain the final /wh... prefix.
            relative = value.lstrip('/')
            if relative.startswith(('PLTV/', 'TVOD/')):
                resolved = prefix + relative
            elif parts.path.startswith(('/PLTV/', '/TVOD/')):
                prefix_parts = urlsplit(prefix)
                resolved = urlunsplit((prefix_parts.scheme, prefix_parts.netloc,
                                       prefix_parts.path + parts.path.lstrip('/'), parts.query, parts.fragment))
        return require_https(resolved)

    def local_url(self, url, local_root):
        parts = urlsplit(require_https(url))
        # Keep DASH variables visible, including variables in directory names.
        variable = parts.path.find('$')
        slash = parts.path.rfind('/', 0, variable + 1) if variable >= 0 else parts.path.rfind('/')
        parent = urlunsplit((parts.scheme, parts.netloc, parts.path[:slash + 1], '', ''))
        tail = parts.path[slash + 1:] + ('?' + parts.query if parts.query else '')
        with self.lock:
            identifier = self.base_ids.get(parent)
            if identifier is None:
                if len(self.bases) >= 4096:
                    raise RelayError('MEDIA_ROUTE_LIMIT')
                identifier = secrets.token_hex(8)
                self.base_ids[parent] = identifier
                self.bases[identifier] = parent
        return local_root + 'r/' + identifier + '/' + tail

    def resource_url(self, identifier, tail):
        with self.lock:
            base = self.bases.get(identifier)
        if (not base or tail.startswith(('/', '\\')) or urlsplit(tail).scheme or
                urlsplit(tail).netloc or '..' in urlsplit(tail).path.split('/')):
            raise RelayError('INVALID_MEDIA_ROUTE')
        return self.resolve(tail, base)

    def rewrite_manifest(self, xml, final_url, local_root):
        try:
            document = parseString(normalize_manifest(xml).encode('utf-8'))
        except RelayError:
            raise
        except Exception:
            raise RelayError('INVALID_MANIFEST_XML') from None
        if document.documentElement.localName != 'MPD':
            raise RelayError('INVALID_MANIFEST_XML')
        normalize_metadata(document)
        inject_default_kids(document)
        url_attributes = {'SegmentTemplate': ('media', 'initialization', 'index', 'bitstreamSwitching'),
                          'SegmentURL': ('media', 'index'), 'Initialization': ('sourceURL',),
                          'RepresentationIndex': ('sourceURL',), 'BitstreamSwitching': ('sourceURL',)}

        def walk(node, base):
            children = [n for n in node.childNodes if n.nodeType == n.ELEMENT_NODE]
            if node.hasAttribute('xml:base'):
                base = self.resolve(node.getAttribute('xml:base'), base)
                node.setAttribute('xml:base', self.local_url(base, local_root))
            bases = [n for n in children if n.localName == 'BaseURL']
            original_bases = []
            for child in bases:
                text = ''.join(n.data for n in child.childNodes if n.nodeType == n.TEXT_NODE).strip()
                original = self.resolve(text, base)
                original_bases.append(original)
                while child.firstChild:
                    child.removeChild(child.firstChild)
                child.appendChild(document.createTextNode(self.local_url(original, local_root)))
            effective = original_bases[0] if original_bases else base
            for attribute in url_attributes.get(node.localName, ()):
                if node.hasAttribute(attribute):
                    node.setAttribute(attribute, self.local_url(self.resolve(node.getAttribute(attribute), effective), local_root))
            for child in children:
                if child.localName == 'Location':
                    while child.firstChild:
                        child.removeChild(child.firstChild)
                    child.appendChild(document.createTextNode(local_root + 'manifest.mpd'))
                elif child.localName != 'BaseURL':
                    walk(child, effective)

        walk(document.documentElement, final_url)
        return document.toxml(encoding='utf-8')

    def manifest(self, local_root, url=None):
        upstream = url or self.manifest_url

        def fetch(target):
            with self.transport.open(target) as response:
                if response.status != 200:
                    raise RelayError('MANIFEST_HTTP_%d' % response.status)
                data = response.read(MAX_MANIFEST + 1)
                if len(data) > MAX_MANIFEST:
                    raise RelayError('MANIFEST_TOO_LARGE')
                if response.headers.get('Content-Encoding', '').lower() == 'gzip':
                    # A bounded decompressor also limits expanded XML size.
                    import io
                    with gzip.GzipFile(fileobj=io.BytesIO(data)) as compressed:
                        data = compressed.read(MAX_MANIFEST + 1)
                    if len(data) > MAX_MANIFEST:
                        raise RelayError('MANIFEST_TOO_LARGE')
                return data.decode('utf-8-sig'), response.geturl()

        xml, final = fetch(upstream)
        retry = browser_mpd_url(upstream, xml)
        if retry != upstream:
            try:
                retry_xml, retry_final = fetch(retry)
                if '<MPD' in retry_xml:
                    xml, final = retry_xml, retry_final
            except Exception:
                # Routing enrichment is optional; preserve a valid first MPD.
                pass
        self.set_final_url(final)
        return self.rewrite_manifest(xml, final, local_root)


class Registry:
    def __init__(self):
        self.secret = secrets.token_urlsafe(32)
        self.contexts = {}
        self.lock = threading.Lock()

    def register(self, stream, transport):
        context = Playback(stream, transport)
        identifier = secrets.token_hex(16)
        with self.lock:
            now = time.monotonic()
            self.contexts = {key: value for key, value in self.contexts.items() if now - value.last_used < 600}
            if len(self.contexts) >= 32:
                oldest = min(self.contexts, key=lambda key: self.contexts[key].last_used)
                del self.contexts[oldest]
            self.contexts[identifier] = context
        return identifier

    def get(self, identifier):
        with self.lock:
            context = self.contexts.get(identifier)
            if context:
                context.last_used = time.monotonic()
            return context


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def error(self, status, code):
        self.server.report(code)
        self.send_response(status)
        self.send_header('Content-Length', '0')
        self.end_headers()

    def route(self):
        # Split without decoding: percent-encoded media/signature bytes matter.
        parts = self.path.split('/', 4)
        if len(parts) < 3 or not secrets.compare_digest(parts[1], self.server.registry.secret):
            raise RelayError('INVALID_LOCAL_ROUTE')
        return parts

    def context(self, parts):
        context = self.server.registry.get(parts[2])
        if context is None:
            raise RelayError('PLAYBACK_EXPIRED')
        local_root = self.server.base + parts[2] + '/'
        return context, local_root

    def do_GET(self):
        try:
            parts = self.route()
            context, root = self.context(parts)
            path = '/'.join(parts[3:])
            if path.split('?', 1)[0] == 'manifest.mpd':
                data = context.manifest(root)
            elif path.startswith('r/'):
                route = path.split('/', 2)
                url = context.resource_url(route[1], route[2])
                if urlsplit(url).path.endswith('.mpd'):
                    data = context.manifest(root, url)
                else:
                    self.forward(context, url)
                    return
            else:
                raise RelayError('INVALID_LOCAL_ROUTE')
            self.send_response(200)
            self.send_header('Content-Type', 'application/dash+xml')
            self.send_header('Content-Length', str(len(data)))
            self.end_headers()
            self.wfile.write(data)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except RelayError as error:
            self.error(502, str(error))
        except Exception:
            self.error(502, 'MEDIA_RELAY_ERROR')

    def forward(self, context, url, data=None, license_request=False):
        with context.transport.open(url, data=data, license_request=license_request,
                                    custom_data=context.custom_data if license_request else '',
                                    headers=dict(self.headers)) as response:
            self.send_response(response.status)
            for key in ('Content-Type', 'Content-Length', 'Content-Range', 'Accept-Ranges',
                        'Content-Encoding', 'Last-Modified', 'ETag'):
                if response.headers.get(key) is not None:
                    self.send_header(key, response.headers[key])
            self.end_headers()
            if response.status >= 400:
                self.server.report(('LICENSE' if license_request else 'SEGMENT') + '_HTTP_%d' % response.status)
            try:
                while True:
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    self.wfile.write(chunk)
            except (BrokenPipeError, ConnectionResetError):
                pass
            except Exception:
                # Headers already went out; terminate the partial response,
                # never append a second HTTP status line to media/license bytes.
                self.close_connection = True
                self.server.report('LICENSE_READ_ERROR' if license_request else 'SEGMENT_READ_ERROR')

    def do_POST(self):
        try:
            parts = self.route()
            length = int(self.headers.get('Content-Length', '0'))
            if length < 0 or length > MAX_LICENSE:
                self.error(413, 'LOCAL_REQUEST_TOO_LARGE')
                return
            data = self.rfile.read(length)
            if parts[2] == 'register' and len(parts) == 3:
                if self.headers.get('Content-Type', '').split(';')[0] != 'application/json':
                    self.error(400, 'INVALID_REGISTRATION')
                    return
                from .api import Client
                client = Client(self.server.profile)
                if not client.logged_in:
                    self.error(409, 'LOGIN_REQUIRED')
                    return
                stream = json.loads(data.decode('utf-8'))
                identifier = self.server.registry.register(stream, Transport(client))
                root = self.server.base + identifier + '/'
                result = json.dumps({'url': root + 'manifest.mpd',
                                     'license': root + 'license' if stream.get('license') else ''}).encode()
                self.send_response(200)
                self.send_header('Content-Type', 'application/json')
                self.send_header('Content-Length', str(len(result)))
                self.end_headers()
                self.wfile.write(result)
            else:
                context, root = self.context(parts)
                if '/'.join(parts[3:]) != 'license' or not context.license_url:
                    raise RelayError('INVALID_LOCAL_ROUTE')
                self.forward(context, context.license_url, data=data, license_request=True)
        except (BrokenPipeError, ConnectionResetError):
            pass
        except RelayError as error:
            self.error(502, str(error))
        except Exception:
            self.error(502, 'LICENSE_RELAY_ERROR')


class Server(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(self, profile, report):
        self.registry = Registry()
        self.profile, self.report = profile, report
        super().__init__(('127.0.0.1', 0), Handler)
        self.base = 'http://127.0.0.1:%d/%s/' % (self.server_port, self.registry.secret)


def register_playback(base, stream):
    parts = urlsplit(base)
    if parts.scheme != 'http' or parts.hostname != '127.0.0.1' or not parts.port or not base.endswith('/'):
        raise RelayError('RELAY_NOT_AVAILABLE')
    request = Request(base + 'register', data=json.dumps(stream).encode('utf-8'),
                      headers={'Content-Type': 'application/json'})
    # This is local IPC only. Upstream requests retain normal proxy/TLS behavior.
    opener = build_opener(ProxyHandler({}))
    try:
        with opener.open(request, timeout=5) as response:
            result = json.loads(response.read(16384).decode('utf-8'))
        if not result.get('url', '').startswith(base):
            raise RelayError('RELAY_INVALID_RESPONSE')
        if result.get('license') and not result['license'].startswith(base):
            raise RelayError('RELAY_INVALID_RESPONSE')
        return result
    except RelayError:
        raise
    except Exception:
        raise RelayError('RELAY_NOT_AVAILABLE') from None
