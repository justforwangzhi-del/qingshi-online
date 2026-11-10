import base64
import http.client
import io
import json
import os
import tempfile
import threading
import time
import unittest
from pathlib import Path
from unittest.mock import patch

os.environ['ACCESS_PASSWORD'] = 'test-access-only'
import fitz
from docx import Document
from PIL import Image
import server
import cloud_gateway as gateway
import pdf_support
import word_export


class OnlineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory()
        pdf_support.CACHE = word_export.EXPORTS = Path(cls.temp.name)
        cls.httpd = server.ThreadingHTTPServer(('127.0.0.1', 0), server.SecureHandler)
        cls.port = cls.httpd.server_port
        threading.Thread(target=cls.httpd.serve_forever, daemon=True).start()

    @classmethod
    def tearDownClass(cls):
        cls.httpd.shutdown()
        cls.httpd.server_close()
        cls.temp.cleanup()

    def request(self, method, path, data=None, auth=True, origin=None):
        c = http.client.HTTPConnection('127.0.0.1', self.port, timeout=10)
        headers = {}
        if auth:
            headers['Authorization'] = 'Basic '+base64.b64encode(b'qingshi:test-access-only').decode()
        if origin:
            headers['Origin'] = origin
        body = json.dumps(data).encode() if data is not None else None
        if body:
            headers['Content-Type'] = 'application/json'
        c.request(method, path, body, headers)
        r = c.getresponse()
        result = r.status, r.read(), dict(r.getheaders())
        c.close()
        return result

    def test_access_and_secrets(self):
        for path in ('/', '/api/provider-config', '/api/pdf-page?token=x', '/api/word-download?id=x'):
            self.assertEqual(self.request('GET', path, auth=False)[0], 401)
        self.assertEqual(self.request('GET', '/healthz', auth=False)[0], 200)
        with patch.dict(gateway.CONFIGS['deepseek'], key='secret-not-for-browser'):
            status, body, _ = self.request('GET', '/api/provider-config')
            self.assertEqual(status, 200)
            self.assertNotIn(b'secret-not-for-browser', body)
            self.assertTrue(json.loads(body)['deepseek']['has_key'])
        for path in ('/api/ocr', '/api/pdf', '/api/export-word'):
            self.assertEqual(self.request('POST', path, {}, origin='https://evil.example')[0], 403)
        self.assertEqual(self.request('POST', '/api/provider-config', {})[0], 404)

    def test_pdf_word_roundtrip(self):
        with fitz.open() as d:
            for n in range(2):
                d.new_page().insert_text((72, 72), 'Test page '+str(n+1))
            pdf = base64.b64encode(d.tobytes()).decode()
        status, body, _ = self.request('POST', '/api/pdf', {'pdf': pdf}, origin=f'http://127.0.0.1:{self.port}')
        self.assertEqual(status, 200, body)
        data = json.loads(body)
        self.assertEqual(data['pages'], 2)
        self.assertEqual(self.request('GET', '/api/pdf-page?token='+data['token']+'&page=2')[0], 200)
        self.assertEqual(self.request('GET', '/api/pdf-page?token='+data['token']+'&page=3')[0], 400)
        payload = {'token': data['token'], 'name': 'test.pdf', 'pages': [{'page': n, 'text': '| A | B |\n| --- | --- |\n| 1 | 2 |'} for n in (1, 2)], 'mode': 'both'}
        status, body, _ = self.request('POST', '/api/export-word', payload)
        self.assertEqual(status, 202, body)
        job = json.loads(body)['id']
        for _ in range(100):
            _, body, _ = self.request('GET', '/api/word-status?id='+job)
            state = json.loads(body)
            if state['state'] != 'building':
                break
            time.sleep(.05)
        self.assertEqual(state['state'], 'done', state)
        status, content, headers = self.request('GET', state['url'])
        self.assertEqual(status, 200)
        self.assertEqual(int(headers['Content-Length']), len(content))
        doc = Document(io.BytesIO(content))
        self.assertEqual(len(doc.inline_shapes), 2)
        self.assertEqual(len(doc.tables), 2)

    def test_cloud_stream_and_consent(self):
        class Response(io.BytesIO):
            status = 200
        class Connection:
            def request(self, method, path, body, headers):
                self.payload = json.loads(body)
            def getresponse(self):
                return Response(b'data: {"choices":[{"delta":{"content":"hello"},"finish_reason":null}]}\n\ndata: {"choices":[{"delta":{},"finish_reason":"stop"}]}\n\ndata: [DONE]\n\n')
            def close(self):
                pass
        image = io.BytesIO()
        Image.new('RGB', (80, 40), 'white').save(image, format='PNG')
        for provider in ('deepseek', 'mimo'):
            payload = {'provider': provider, 'image': base64.b64encode(image.getvalue()).decode(), 'prompt': 'read', 'cloud_consent': True}
            connection = Connection()
            with patch.dict(gateway.CONFIGS[provider], key='test-key'), patch.object(gateway, 'connect', return_value=(connection, '/v1')):
                status, body, _ = self.request('POST', '/api/ocr', payload)
                self.assertEqual(status, 200, body)
                events = [json.loads(line) for line in body.splitlines()]
                self.assertEqual(events[0]['response'], 'hello')
                self.assertTrue(events[-1]['done'])
                payload['cloud_consent'] = False
                self.assertEqual(self.request('POST', '/api/ocr', payload)[0], 400)
        self.assertEqual(self.request('POST', '/api/ocr', {'image': 'bad'})[0], 400)
