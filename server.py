import base64
import hmac
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import urlsplit

from cloud_gateway import cloud_ocr, public_config
from pdf_support import pdf_handler, CACHE, DOCS, GUARD
from word_export import word_handler, EXPORTS, JOBS, JOB_LOCK

ROOT = Path(__file__).resolve().parent
PORT = int(os.environ.get('PORT', '8787'))
LOCK = threading.Lock()

class Handler(BaseHTTPRequestHandler):
    protocol_version = 'HTTP/1.1'

    def setup(self):
        super().setup()
        self.connection.settimeout(360)

    def reply(self, status, data, content_type='application/json; charset=utf-8'):
        body = data if isinstance(data, bytes) else json.dumps(data, ensure_ascii=False).encode()
        if status >= 400:
            self.close_connection = True
        self.send_response(status)
        self.send_header('Content-Type', content_type)
        self.send_header('Content-Length', str(len(body)))
        self.send_header('Cache-Control', 'no-store')
        self.send_header('X-Content-Type-Options', 'nosniff')
        self.send_header('Referrer-Policy', 'same-origin')
        self.send_header('X-Frame-Options', 'DENY')
        if self.close_connection:
            self.send_header('Connection', 'close')
        self.end_headers()
        self.wfile.write(body)

    def valid_origin(self, origin):
        public = os.environ.get('PUBLIC_URL', '').rstrip('/')
        if public:
            return origin == public
        parsed = urlsplit(origin)
        return parsed.scheme in ('http', 'https') and parsed.netloc == self.headers.get('Host')

    def do_GET(self):
        if self.path in ('/', '/index.html'):
            return self.reply(200, (ROOT/'index.html').read_bytes(), 'text/html; charset=utf-8')
        if self.path == '/api/provider-config':
            return self.reply(200, public_config())
        self.reply(404, {'error': '页面不存在'})

    def do_POST(self):
        if self.path != '/api/ocr':
            return self.reply(404, {'error': '接口不存在'})
        try:
            length = int(self.headers.get('Content-Length', 0))
            if not 0 < length <= 22 * 1024 * 1024:
                return self.reply(413, {'error': '请选择15MB以内的图片。'})
            data = json.loads(self.rfile.read(length))
            decoded = base64.b64decode(data.get('image', ''), validate=True)
            if len(decoded) > 15 * 1024 * 1024:
                raise ValueError('图片不能超过15MB。')
            from PIL import Image
            import io
            with Image.open(io.BytesIO(decoded)) as img:
                if img.format not in ('PNG', 'JPEG', 'WEBP') or img.width*img.height > 25000000:
                    raise ValueError('请选择2500万像素以内的PNG、JPEG或WebP图片。')
                img.verify()
            prompt = str(data.get('prompt', '')).strip()[:4000] or '识别图片文字并以 Markdown 输出。'
        except Exception:
            return self.reply(400, {'error': '图片数据无效或过大，请重新上传。'})
        return cloud_ocr(self, data, decoded, prompt, LOCK)

# The outer handler protects every route, including PDF previews and Word downloads.
class SecureHandler(word_handler(pdf_handler(Handler))):
    def parse_request(self):
        if not super().parse_request():
            return False
        if self.command == 'GET' and self.path == '/healthz':
            self.reply(200, {'ok': True})
            return False
        password = os.environ.get('ACCESS_PASSWORD', '')
        username = os.environ.get('ACCESS_USERNAME', 'qingshi')
        expected = 'Basic '+base64.b64encode((username+':'+password).encode()).decode()
        if not password or not hmac.compare_digest(self.headers.get('Authorization', '').encode(), expected.encode()):
            self.close_connection = True
            self.send_response(401)
            self.send_header('WWW-Authenticate', 'Basic realm="QingShi", charset="UTF-8"')
            self.send_header('Content-Length', '0')
            self.end_headers()
            return False
        if self.command not in ('GET', 'POST'):
            self.reply(405, {'error': '不支持此请求'})
            self.close_connection = True
            return False
        if self.command == 'POST':
            origin = self.headers.get('Origin')
            if origin and not self.valid_origin(origin):
                self.reply(403, {'error': '不允许此来源'})
                self.close_connection = True
                return False
            try:
                size = int(self.headers.get('Content-Length', '0'))
                if self.headers.get('Transfer-Encoding') or not 0 < size <= 42*1024*1024:
                    raise ValueError()
            except ValueError:
                self.reply(413, {'error': '请求内容过大或长度无效'})
                self.close_connection = True
                return False
        return True

    def log_message(self, fmt, *args):
        # Query strings contain temporary file tokens; do not put them in logs.
        print('%s %s' % (self.command, urlsplit(self.path).path), flush=True)


def cleanup():
    while True:
        cutoff = time.time()-86400
        for folder, pattern in ((CACHE, '*.pdf'), (EXPORTS, '*.docx')):
            for path in folder.glob(pattern):
                try:
                    if path.stat().st_mtime < cutoff:
                        path.unlink(missing_ok=True)
                except OSError:
                    pass
        with GUARD:
            for key in list(DOCS):
                if DOCS[key][1] < cutoff:
                    del DOCS[key]
        with JOB_LOCK:
            for key in list(JOBS):
                if JOBS[key]['created'] < cutoff and JOBS[key]['state'] != 'building':
                    del JOBS[key]
        time.sleep(300)

if __name__ == '__main__':
    if not os.environ.get('ACCESS_PASSWORD'):
        raise SystemExit('请设置 ACCESS_PASSWORD 后启动。')
    threading.Thread(target=cleanup, daemon=True).start()
    print(f'QingShi online listening on {PORT}', flush=True)
    ThreadingHTTPServer(('0.0.0.0', PORT), SecureHandler).serve_forever()
