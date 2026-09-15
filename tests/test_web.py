import json
from pathlib import Path
import socket
from tempfile import TemporaryDirectory
import unittest
from unittest.mock import Mock, patch

from jarvis.tools import create_local_tools
from jarvis.tools.web import PublicHTTPS, WebClient, WebError, validate_url
from jarvis.brain import Agent


def document(body, content_type='text/html', url='https://example.com/'):
    if isinstance(body, str):
        body = body.encode('utf-8')
    return {'body': body, 'content_type': content_type, 'url': url}


class PublicHTTPSTests(unittest.TestCase):
    def test_url_restrictions(self):
        for url in ['file:///secret', 'http://example.com', 'https://user:pass@example.com',
                    'https://localhost/', 'https://server.local/', 'https://example.com:8443',
                    'https://example.com/\nheader', 'https://example.com\\@localhost/']:
            with self.subTest(url=url), self.assertRaises(WebError):
                validate_url(url)
        self.assertEqual(validate_url('https://example.com/docs?q=a')[1], 'example.com')

    def test_nonpublic_dns_addresses_are_blocked_before_connection(self):
        for ip in ['127.0.0.1', '10.0.0.1', '192.168.1.1', '169.254.169.254', '::1', 'fc00::1']:
            records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443))]
            with self.subTest(ip=ip), patch('socket.getaddrinfo', return_value=records), \
                    patch('socket.create_connection') as connect:
                with self.assertRaisesRegex(WebError, 'addresses are blocked'):
                    PublicHTTPS().get('https://example.com/')
                connect.assert_not_called()

    def _network(self, response):
        connection = Mock()
        connection.getresponse.return_value = response
        return connection

    def test_tls_uses_validated_ip_and_original_hostname(self):
        response = Mock(status=200)
        response.getheader.side_effect = lambda name, default=None: {'Content-Type': 'text/plain'}.get(name, default)
        response.read1.side_effect = [b'hello', b'']
        connection = self._network(response)
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]
        with patch('socket.getaddrinfo', return_value=records) as dns, \
                patch('socket.create_connection') as connect, \
                patch('ssl.create_default_context') as tls, \
                patch('http.client.HTTPSConnection', return_value=connection):
            result = PublicHTTPS().get('https://example.com/test')
        self.assertEqual(result['body'], b'hello')
        dns.assert_called_once()
        self.assertEqual(connect.call_args.args[0], ('93.184.216.34', 443))
        self.assertEqual(tls.return_value.wrap_socket.call_args.kwargs['server_hostname'], 'example.com')
        connection.close.assert_called_once()

    def test_redirect_to_private_address_is_rejected(self):
        response = Mock(status=302)
        response.getheader.return_value = 'https://127.0.0.1/'
        records = lambda ip: [(socket.AF_INET, socket.SOCK_STREAM, 6, '', (ip, 443))]
        with patch('socket.getaddrinfo', side_effect=[records('93.184.216.34'), records('127.0.0.1')]), \
                patch('socket.create_connection') as connect, patch('ssl.create_default_context'), \
                patch('http.client.HTTPSConnection', return_value=self._network(response)):
            with self.assertRaisesRegex(WebError, 'addresses are blocked'):
                PublicHTTPS().get('https://example.com/')
            self.assertEqual(connect.call_count, 1)

    def test_oversized_response_is_rejected(self):
        response = Mock(status=200)
        response.getheader.side_effect = lambda name, default=None: default
        response.read1.return_value = b'12345'
        records = [(socket.AF_INET, socket.SOCK_STREAM, 6, '', ('93.184.216.34', 443))]
        with patch('socket.getaddrinfo', return_value=records), patch('socket.create_connection'), \
                patch('ssl.create_default_context'), \
                patch('http.client.HTTPSConnection', return_value=self._network(response)):
            with self.assertRaisesRegex(WebError, 'download limit'):
                PublicHTTPS(max_bytes=4).get('https://example.com/')

    def test_offline_error_is_actionable(self):
        with patch('socket.getaddrinfo', side_effect=socket.gaierror('offline')):
            with self.assertRaisesRegex(WebError, 'local chat and tools remain available'):
                PublicHTTPS().get('https://example.com/')


class WebToolTests(unittest.TestCase):
    def setUp(self):
        self.transport = Mock()
        self.web = WebClient(self.transport)

    def test_search_results_include_sources_dates_and_encoded_query(self):
        self.transport.get.return_value = document('''<rss><channel><item>
            <title>Release</title><link>https://example.com/release</link>
            <description>&lt;b&gt;New version&lt;/b&gt;</description>
            <pubDate>Fri, 11 Sep 2026 00:00:00 GMT</pubDate>
            </item></channel></rss>''', 'application/rss+xml')
        result = self.web.web_search('release & docs')
        self.assertIn('q=release+%26+docs', self.transport.get.call_args.args[0])
        self.assertEqual(result['results'][0]['snippet'], 'New version')
        self.assertIn('published_at', result['results'][0])
        self.assertIn('retrieved_at', result)
        self.web.news_search('release')
        self.assertIn('news.google.com/rss/search?', self.transport.get.call_args.args[0])

    def test_provider_block_page_and_entities_are_rejected(self):
        for body in ['<html>Bot challenge</html>', '<!DOCTYPE rss><rss/>', 'broken xml']:
            with self.subTest(body=body):
                self.transport.get.return_value = document(body)
                with self.assertRaises(WebError):
                    self.web.web_search('docs')

    def test_irrelevant_web_results_fall_back_to_news_search(self):
        irrelevant = document('''<rss><channel><item><title>Regional headlines</title>
            <link>https://example.com/local</link><description>Unrelated stories</description>
            </item></channel></rss>''', 'application/rss+xml')
        fallback = document('''<rss><channel><item><title>Python release announced</title>
            <link>https://example.com/python</link><description>Python version details</description>
            </item></channel></rss>''', 'application/rss+xml')
        self.transport.get.side_effect = [irrelevant, fallback]
        result = self.web.web_search('latest Python release')
        self.assertEqual(result['provider'], 'Google News fallback')
        self.assertEqual(result['results'][0]['url'], 'https://example.com/python')
        self.assertEqual(self.transport.get.call_count, 2)

    def test_page_extraction_removes_scripts_and_caps_output(self):
        self.transport.get.return_value = document('<title>Docs</title><script>bad()</script><p>' + 'x' * 17000 + '</p>')
        result = self.web.read_web('https://example.com/')
        self.assertEqual(result['title'], 'Docs')
        self.assertNotIn('bad()', result['text'])
        self.assertEqual(len(result['text']), 16000)
        self.assertTrue(result['truncated'])

    def test_json_api_and_unsupported_content(self):
        self.transport.get.return_value = document('{"version":"1.2"}', 'application/json')
        self.assertEqual(json.loads(self.web.read_web('https://example.com/api')['text']), {'version': '1.2'})
        self.transport.get.return_value = document('broken', 'application/json')
        with self.assertRaisesRegex(WebError, 'invalid JSON'):
            self.web.read_web('https://example.com/api')
        self.transport.get.return_value = document(b'%PDF', 'application/pdf')
        with self.assertRaisesRegex(WebError, 'Only HTML'):
            self.web.read_web('https://example.com/file')

    def test_weather_resolves_location_and_preserves_units(self):
        self.transport.get.side_effect = [document(json.dumps({'results': [
            {'name': 'Taipei', 'country': 'Taiwan', 'latitude': 25.0, 'longitude': 121.5}]})),
            document(json.dumps({'current': {'temperature_2m': 29}, 'current_units': {'temperature_2m': 'C'},
                                 'daily': {'temperature_2m_max': [30]}, 'timezone': 'Asia/Taipei'}))]
        result = self.web.get_weather('Taipei')
        self.assertEqual(result['location']['country'], 'Taiwan')
        self.assertEqual(result['current_units']['temperature_2m'], 'C')
        self.assertIn('latitude=25.0', self.transport.get.call_args.args[0])
        self.assertEqual(result['provider'], 'Open-Meteo')

    def test_missing_weather_location(self):
        self.transport.get.return_value = document('{}', 'application/json')
        with self.assertRaisesRegex(WebError, 'Location not found'):
            self.web.get_weather('nowhere')

    def test_disabled_web_never_requests_network_and_local_tools_work(self):
        with TemporaryDirectory() as directory:
            registry = create_local_tools(Path(directory), web=WebClient(self.transport, enabled=False))
            for name, args in [('web_search', {'query': 'hello'}), ('news_search', {'query': 'news'}),
                               ('read_web', {'url': 'https://example.com/'}), ('get_weather', {'location': 'Taipei'})]:
                with self.subTest(tool=name):
                    result = registry.execute(name, args)
                    self.assertFalse(result['ok'])
                    self.assertIn('disabled', result['error'])
            self.assertTrue(registry.execute('get_time', {})['ok'])
        self.transport.get.assert_not_called()

    def test_agent_receives_web_error_and_can_reply(self):
        model = Mock()
        model.chat_message_stream.side_effect = [
            {'role': 'assistant', 'content': '', 'tool_calls': [
                {'function': {'name': 'web_search', 'arguments': {'query': 'news'}}}]},
            {'role': 'assistant', 'content': 'Current news could not be verified.'},
        ]
        with TemporaryDirectory() as directory:
            registry = create_local_tools(Path(directory), web=WebClient(self.transport, enabled=False))
            agent = Agent(model, tools=registry)
            self.assertIn('could not be verified', agent.respond_stream('News?', lambda token: None))
            self.assertFalse(json.loads(agent.messages[-2]['content'])['ok'])
