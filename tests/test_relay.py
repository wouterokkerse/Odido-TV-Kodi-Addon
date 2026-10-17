"""Redirect/MPD/relay regression tests with in-memory upstream responses.

No subscriber traffic is involved. Handler tests invoke HTTP handler methods
without sockets because this execution sandbox disallows loopback sockets.
"""
import base64
from concurrent.futures import ThreadPoolExecutor
import gzip
import http.cookiejar
import io
import json
from pathlib import Path
import sys
import tempfile
import threading
import types
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit
from urllib.request import Request
import uuid
from xml.dom.minidom import parseString

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'plugin.video.odidotv'))
from resources.lib.api import Client
from resources.lib.relay import Playback, Transport, Registry, Handler, ScopedRedirects, RelayError, browser_mpd_url, register_playback

ROOT = 'http://127.0.0.1:12345/secret/playback/'
INITIAL = 'https://lb.tvx.prd.tv.odido.nl/PLTV/86/224/42/manifest.mpd?sig=a%2Bb'
FINAL = 'https://mag01.tvx.prd.tv.odido.nl/wh123/PLTV/86/224/42/manifest.mpd?sig=a%2Bb'


class Response(io.BytesIO):
    def __init__(self, body=b'', url=FINAL, status=200, headers=None):
        super().__init__(body)
        self.url, self.status = url, status
        self.headers = headers or {}
        self.read_sizes = []

    def read(self, size=-1):
        self.read_sizes.append(size)
        return super().read(size)

    def geturl(self):
        return self.url


def playback(transport=None, initial=INITIAL):
    return Playback({'url': initial, 'license': 'https://tv.odido.nl/VSP/V3/ExternalDRMLicense',
                     'custom_data': 'opaque-license-data'}, transport or Mock())


def remote_url(context, local):
    tail = local.split('/r/', 1)[1]
    identifier, tail = tail.split('/', 1)
    return context.resource_url(identifier, tail)


class ManifestTests(unittest.TestCase):
    def test_final_redirect_prefix_used_for_root_relative_segments(self):
        xml = '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period><AdaptationSet><SegmentTemplate media="/PLTV/86/v-$Time$.dash?sig=a%2Bb" initialization="/PLTV/86/init.dash"/></AdaptationSet></Period></MPD>'
        transport = Mock()
        transport.open.return_value = Response(xml.encode())
        context = playback(transport)
        result = parseString(context.manifest(ROOT))
        segment = result.getElementsByTagName('SegmentTemplate')[0]
        self.assertEqual(remote_url(context, segment.getAttribute('media').replace('$Time$', '3000')),
                         'https://mag01.tvx.prd.tv.odido.nl/wh123/PLTV/86/v-3000.dash?sig=a%2Bb')
        self.assertIn('/wh123/PLTV/', remote_url(context, segment.getAttribute('initialization')))

    def test_absolute_load_balancer_and_pltv_relative_urls_rebased(self):
        context = playback()
        context.set_final_url(FINAL)
        for value in ('PLTV/86/segment.dash', '/PLTV/86/segment.dash',
                      'https://lb.tvx.prd.tv.odido.nl/PLTV/86/segment.dash'):
            self.assertEqual(context.resolve(value, FINAL),
                             'https://mag01.tvx.prd.tv.odido.nl/wh123/PLTV/86/segment.dash')

    def test_nested_base_urls_and_directory_template_variables(self):
        xml = '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><BaseURL>/PLTV/86/</BaseURL><Period><AdaptationSet><BaseURL>video/</BaseURL><SegmentTemplate media="$RepresentationID$/chunk-$Number%05d$.m4s?token=x%2By"/></AdaptationSet></Period></MPD>'
        context = playback()
        context.set_final_url(FINAL)
        document = parseString(context.rewrite_manifest(xml, FINAL, ROOT))
        template = document.getElementsByTagName('SegmentTemplate')[0].getAttribute('media')
        self.assertIn('$RepresentationID$', template)
        self.assertIn('$Number%05d$', template)
        resolved = remote_url(context, template.replace('$RepresentationID$', '720').replace('$Number%05d$', '00002'))
        self.assertEqual(resolved, 'https://mag01.tvx.prd.tv.odido.nl/wh123/PLTV/86/video/720/chunk-00002.m4s?token=x%2By')

    def test_single_file_base_url_and_segment_list_index_rewritten(self):
        xml = '<MPD><Period><AdaptationSet><Representation><BaseURL>video.mp4?sig=x%2By</BaseURL><SegmentList><Initialization sourceURL="init.mp4"/><SegmentURL media="part.mp4" index="part.idx"/></SegmentList></Representation></AdaptationSet></Period></MPD>'
        context = playback()
        document = parseString(context.rewrite_manifest(xml, FINAL, ROOT))
        file_url = document.getElementsByTagName('BaseURL')[0].firstChild.data
        self.assertEqual(remote_url(context, file_url), FINAL.split('manifest.mpd')[0] + 'video.mp4?sig=x%2By')
        segment = document.getElementsByTagName('SegmentURL')[0]
        self.assertTrue(segment.getAttribute('media').startswith(ROOT))
        self.assertTrue(segment.getAttribute('index').startswith(ROOT))

    def test_all_periods_representations_and_pssh_preserved(self):
        xml = '<MPD xmlns:cenc="urn:mpeg:cenc:2013"><Period id="one"><AdaptationSet><ContentProtection schemeIdUri="urn:uuid:edef8ba9-79d6-4ace-a3c8-27dcd51d21ed"><cenc:pssh>opaque-pssh</cenc:pssh></ContentProtection><Representation id="720"/><Representation id="1080"/></AdaptationSet></Period><Period id="two"/></MPD>'
        result = parseString(playback().rewrite_manifest(xml, FINAL, ROOT))
        self.assertEqual(len(result.getElementsByTagName('Period')), 2)
        self.assertEqual(len(result.getElementsByTagName('Representation')), 2)
        self.assertEqual(result.getElementsByTagName('cenc:pssh')[0].firstChild.data, 'opaque-pssh')

    def test_missing_default_kid_copied_from_public_playready_header(self):
        kid = uuid.UUID('00112233-4455-6677-8899-aabbccddeeff')
        encoded_kid = base64.b64encode(kid.bytes_le).decode()
        pro = base64.b64encode(('<WRMHEADER><DATA><KID>' + encoded_kid + '</KID></DATA></WRMHEADER>').encode('utf-16-le')).decode()
        xml = '<MPD xmlns:mspr="urn:microsoft:playready"><Period><AdaptationSet><ContentProtection schemeIdUri="urn:mpeg:dash:mp4protection:2011"/><ContentProtection schemeIdUri="urn:uuid:9a04f079-9840-4286-ab92-e65be0885f95"><mspr:pro>' + pro + '</mspr:pro></ContentProtection></AdaptationSet></Period></MPD>'
        result = parseString(playback().rewrite_manifest(xml, FINAL, ROOT))
        self.assertEqual(result.getElementsByTagName('ContentProtection')[0].getAttribute('cenc:default_KID'), str(kid))
        self.assertEqual(result.getElementsByTagName('mspr:pro')[0].firstChild.data, pro)

    def test_existing_default_kid_not_changed(self):
        xml = '<MPD xmlns:cenc="urn:mpeg:cenc:2013"><Period><AdaptationSet><ContentProtection cenc:default_KID="existing"/></AdaptationSet></Period></MPD>'
        result = playback().rewrite_manifest(xml, FINAL, ROOT)
        self.assertIn(b'cenc:default_KID="existing"', result)

    def test_unprefixed_pssh_normalized_without_changing_payload(self):
        xml = '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period><AdaptationSet><ContentProtection><pssh>opaque</pssh></ContentProtection><AudioChannelConfiguration schemeIdUri="tag:dolby.com,2014:dash:audio_channel_configuration:2011" value="6"/></AdaptationSet></Period></MPD>'
        result = parseString(playback().rewrite_manifest(xml, FINAL, ROOT))
        self.assertEqual(result.getElementsByTagNameNS('urn:mpeg:cenc:2013', 'pssh')[0].firstChild.data, 'opaque')
        audio = result.getElementsByTagName('AudioChannelConfiguration')[0]
        self.assertEqual(audio.getAttribute('schemeIdUri'), 'urn:dolby:dash:audio_channel_configuration:2011')
        self.assertEqual(audio.getAttribute('value'), '6')

    def test_refresh_location_stays_on_local_manifest(self):
        result = parseString(playback().rewrite_manifest('<MPD><Location>https://lb.example/next.mpd</Location></MPD>', FINAL, ROOT))
        self.assertEqual(result.getElementsByTagName('Location')[0].firstChild.data, ROOT + 'manifest.mpd')

    def test_refresh_adopts_new_redirect_target_without_changing_old_routes(self):
        context = playback()
        context.set_final_url(FINAL)
        old = context.local_url(FINAL.split('manifest.mpd')[0] + 'chunk.m4s', ROOT)
        new_final = FINAL.replace('mag01', 'mag02').replace('wh123', 'wh456')
        context.set_final_url(new_final)
        self.assertIn('mag01', remote_url(context, old))
        self.assertIn('/wh456/', context.resolve('/PLTV/86/new.m4s', new_final))

    def test_browser_routing_params_appended_without_reserializing_signature(self):
        xml = '<MPD><BaseURL>https://cdn.example/?service_devid=1008&amp;mag_hms=1008,311&amp;online=123</BaseURL></MPD>'
        url = browser_mpd_url(INITIAL + '&duplicate=one&duplicate=two', xml)
        self.assertTrue(url.startswith(INITIAL + '&duplicate=one&duplicate=two&'))
        self.assertIn('hms_devid=1008', url)
        self.assertIn('RTS=123', url)
        self.assertIn('from=14', url)
        self.assertEqual(browser_mpd_url(url, xml), url)

    def test_no_routing_fields_leaves_url_unchanged(self):
        self.assertEqual(browser_mpd_url(INITIAL, '<MPD/>'), INITIAL)

    def test_optional_retry_failure_keeps_first_valid_manifest(self):
        xml = '<MPD><BaseURL>https://cdn.example/?service_devid=1008&amp;mag_hms=1008&amp;online=123</BaseURL></MPD>'
        transport = Mock()
        transport.open.side_effect = [Response(xml.encode()), Response(b'refused', status=403)]
        result = playback(transport).manifest(ROOT)
        self.assertIn(b'MPD', result)
        self.assertEqual(transport.open.call_count, 2)

    def test_manifest_failure_uses_code_without_remote_url(self):
        transport = Mock()
        transport.open.return_value = Response(b'private account response', status=403)
        with self.assertRaisesRegex(RelayError, '^MANIFEST_HTTP_403$'):
            playback(transport).manifest(ROOT)

    def test_gzipped_manifest_supported(self):
        transport = Mock()
        transport.open.return_value = Response(gzip.compress(b'<MPD/>'), headers={'Content-Encoding': 'gzip'})
        self.assertIn(b'MPD', playback(transport).manifest(ROOT))

    def test_entity_declarations_rejected(self):
        with self.assertRaises(RelayError):
            playback().rewrite_manifest('<!DOCTYPE MPD [<!ENTITY test "expanded">]><MPD/>', FINAL, ROOT)

    def test_invalid_resource_routes_rejected(self):
        context = playback()
        url = context.local_url('https://cdn.example/path/segment.m4s', ROOT)
        identifier = url.split('/r/')[1].split('/')[0]
        for tail in ('//elsewhere.example/file', 'https://elsewhere.example/file', '../secret'):
            with self.assertRaises(RelayError):
                context.resource_url(identifier, tail)


class TransportTests(unittest.TestCase):
    def client(self):
        return types.SimpleNamespace(jar=[], state={'csrf_token': 'private-csrf'})

    def test_license_headers_upstream_exclude_local_host_and_content_length(self):
        transport = Transport(self.client())
        opener = Mock()
        opener.open.return_value = Response(b'license')
        with patch('resources.lib.relay.build_opener', return_value=opener):
            transport.open('https://tv.odido.nl/VSP/V3/ExternalDRMLicense', data=b'challenge',
                           license_request=True, custom_data='opaque',
                           headers={'Host': '127.0.0.1:12345', 'Content-Length': '999', 'Range': 'bytes=0-99'})
        request = opener.open.call_args.args[0]
        headers = {key.lower(): value for key, value in request.header_items()}
        self.assertNotIn('host', headers)
        self.assertNotIn('content-length', headers)
        self.assertEqual(headers['x_csrftoken'], 'private-csrf')
        self.assertEqual(headers['acquirelicense.customdata'], 'opaque')
        self.assertEqual(headers['range'], 'bytes=0-99')
        self.assertEqual(request.data, b'challenge')

    def test_segments_do_not_receive_license_custom_data_or_csrf(self):
        opener = Mock()
        with patch('resources.lib.relay.build_opener', return_value=opener):
            Transport(self.client()).open('https://cdn.example/chunk.m4s', custom_data='opaque')
        headers = {key.lower(): value for key, value in opener.open.call_args.args[0].header_items()}
        self.assertNotIn('x_csrftoken', headers)
        self.assertNotIn('acquirelicense.customdata', headers)
        self.assertEqual(headers['origin'], 'https://tv.odido.nl')

    def test_cross_host_redirect_drops_sensitive_headers(self):
        request = Request('https://tv.odido.nl/start', headers={'X_CSRFToken': 'private',
                          'Cookie': 'private', 'AcquireLicense.CustomData': 'private', 'User-Agent': 'test'})
        redirected = ScopedRedirects().redirect_request(request, None, 302, '', {}, 'https://cdn.example/final')
        headers = {key.lower(): value for key, value in redirected.header_items()}
        self.assertNotIn('x_csrftoken', headers)
        self.assertNotIn('cookie', headers)
        self.assertNotIn('acquirelicense.customdata', headers)
        self.assertEqual(headers['user-agent'], 'test')

    def test_plain_http_upstream_redirect_rejected(self):
        with self.assertRaises(RelayError):
            ScopedRedirects().redirect_request(Request('https://tv.odido.nl/start'), None, 302, '', {}, 'http://cdn.example/final')

    def test_local_registration_rejects_external_addresses(self):
        with self.assertRaises(RelayError):
            register_playback('http://remote.example/secret/', {'url': INITIAL})


class HandlerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.registry = Registry()
        self.base = 'http://127.0.0.1:12345/' + self.registry.secret + '/'
        self.server = types.SimpleNamespace(registry=self.registry, base=self.base,
                                            report=Mock(), profile=self.directory.name)

    def handler(self, path, data=b'', headers=None):
        handler = Handler.__new__(Handler)
        handler.server = self.server
        handler.path = '/' + self.registry.secret + '/' + path
        handler.headers = dict(headers or {})
        handler.headers.setdefault('Content-Length', str(len(data)))
        handler.rfile, handler.wfile = io.BytesIO(data), io.BytesIO()
        handler.send_response, handler.send_header, handler.end_headers = Mock(), Mock(), Mock()
        return handler

    def test_register_to_manifest_to_segment_flow(self):
        client = Client(self.directory.name, transport=lambda *args: {'result': {'retCode': '000000000'}, 'csrfToken': 'test'})
        client.login('synthetic', 'test')
        transport = Mock()
        transport.open.side_effect = [Response(b'<MPD><Period><AdaptationSet><SegmentTemplate media="/PLTV/86/chunk-$Time$.m4s"/></AdaptationSet></Period></MPD>'), Response(b'segment bytes', headers={'Content-Length': '13'})]
        stream = {'url': INITIAL, 'license': ''}
        register = self.handler('register', json.dumps(stream).encode(), {'Content-Type': 'application/json'})
        with patch('resources.lib.relay.Transport', return_value=transport):
            register.do_POST()
        result = json.loads(register.wfile.getvalue())
        manifest = self.handler(result['url'].split(self.base)[1])
        manifest.do_GET()
        manifest.send_response.assert_called_once_with(200)
        xml = parseString(manifest.wfile.getvalue())
        local_segment = xml.getElementsByTagName('SegmentTemplate')[0].getAttribute('media').replace('$Time$', '1')
        segment = self.handler(local_segment.split(self.base)[1])
        segment.do_GET()
        self.assertEqual(segment.wfile.getvalue(), b'segment bytes')
        self.assertEqual(transport.open.call_args.args[0], 'https://mag01.tvx.prd.tv.odido.nl/wh123/PLTV/86/chunk-1.m4s')

    def test_binary_license_forwarding(self):
        transport = Mock()
        transport.open.return_value = Response(b'\x00binary\xfflicense', headers={'Content-Type': 'application/octet-stream'})
        identifier = self.registry.register({'url': INITIAL, 'license': 'https://tv.odido.nl/license', 'custom_data': 'opaque'}, transport)
        handler = self.handler(identifier + '/license', b'\x00challenge\xff')
        handler.do_POST()
        self.assertEqual(handler.wfile.getvalue(), b'\x00binary\xfflicense')
        self.assertEqual(transport.open.call_args.kwargs['data'], b'\x00challenge\xff')
        self.assertTrue(transport.open.call_args.kwargs['license_request'])
        self.assertEqual(transport.open.call_args.kwargs['custom_data'], 'opaque')

    def test_large_segment_forwarded_in_chunks_with_range(self):
        response = Response(b'x' * 200000, status=206, headers={'Content-Range': 'bytes 0-199999/500000'})
        context = playback()
        context.transport.open.return_value = response
        handler = self.handler('unused', headers={'Range': 'bytes=0-199999'})
        handler.forward(context, 'https://cdn.example/chunk.m4s')
        self.assertEqual(len(handler.wfile.getvalue()), 200000)
        self.assertTrue(all(size == 65536 for size in response.read_sizes))
        handler.send_response.assert_called_once_with(206)
        handler.send_header.assert_any_call('Content-Range', 'bytes 0-199999/500000')
        self.assertEqual(context.transport.open.call_args.kwargs['headers']['Range'], 'bytes=0-199999')

    def test_interrupted_segment_does_not_send_second_http_response(self):
        response = Response(b'partial')
        response.read = Mock(side_effect=[b'partial', OSError('network interrupted')])
        context = playback()
        context.transport.open.return_value = response
        handler = self.handler('unused')
        handler.forward(context, 'https://cdn.example/chunk.m4s')
        handler.send_response.assert_called_once_with(200)
        self.assertEqual(handler.wfile.getvalue(), b'partial')
        self.server.report.assert_called_once_with('SEGMENT_READ_ERROR')

    def test_concurrent_channel_contexts_keep_separate_media_bases(self):
        one = self.registry.register({'url': INITIAL}, Mock())
        two = self.registry.register({'url': INITIAL.replace('/42/', '/43/')}, Mock())
        first, second = self.registry.get(one), self.registry.get(two)
        with ThreadPoolExecutor(max_workers=2) as executor:
            list(executor.map(lambda pair: pair[0].set_final_url(pair[1]),
                              [(first, FINAL), (second, FINAL.replace('mag01', 'mag02').replace('wh123', 'wh456'))]))
        self.assertIn('/wh123/', first.resolve('/PLTV/86/chunk.m4s', FINAL))
        self.assertIn('/wh456/', second.resolve('/PLTV/86/chunk.m4s', FINAL.replace('mag01', 'mag02')))

    def test_invalid_local_token_sends_no_upstream_request(self):
        handler = self.handler('unused/manifest.mpd')
        handler.path = '/wrong-token/unused/manifest.mpd'
        handler.do_GET()
        handler.send_response.assert_called_once_with(502)
        self.server.report.assert_called_once_with('INVALID_LOCAL_ROUTE')

    def test_registration_without_login_rejected(self):
        handler = self.handler('register', json.dumps({'url': INITIAL}).encode(), {'Content-Type': 'application/json'})
        handler.do_POST()
        handler.send_response.assert_called_once_with(409)
        self.assertFalse(self.registry.contexts)


if __name__ == '__main__':
    unittest.main()
