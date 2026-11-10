import base64
import json
import secrets
import threading
import time
from pathlib import Path
import re
from urllib.parse import urlsplit, parse_qs
import fitz

DOCS = {}
GUARD = threading.Lock()
CACHE = Path(__file__).parent/'pdf-cache'
CACHE.mkdir(exist_ok=True)

def load_source(token):
    if not isinstance(token,str) or not re.fullmatch(r'[\w-]{20,80}',token):
        raise ValueError('PDF缓存标识无效。')
    with GUARD:
        entry=DOCS.get(token)
        if entry and time.time()-entry[1]<=86400:
            return entry[0]
    path=CACHE/(token+'.pdf')
    if path.exists() and time.time()-path.stat().st_mtime<=86400:
        return path.read_bytes()
    raise ValueError('PDF缓存已过期，请重新上传并识别。')

def pdf_handler(Base):
    class PDFHandler(Base):
        def do_GET(self):
            parsed = urlsplit(self.path)
            if parsed.path != '/api/pdf-page':
                return super().do_GET()
            try:
                query = parse_qs(parsed.query)
                token = query.get('token', [''])[0]
                page_num = int(query.get('page', ['1'])[0])
                source = load_source(token)
                with fitz.open(stream=source, filetype='pdf') as doc:
                    if not 1 <= page_num <= len(doc):
                        raise ValueError('页码超出范围。')
                    page = doc[page_num-1]
                    longest = max(page.rect.width, page.rect.height)
                    if longest <= 0:
                        raise ValueError('PDF页面尺寸无效。')
                    pix = page.get_pixmap(matrix=fitz.Matrix(2000/longest, 2000/longest), alpha=False)
                    image = base64.b64encode(pix.tobytes('png')).decode()
                self.reply(200, {'image': image, 'page': page_num})
            except Exception as exc:
                self.reply(400, {'error': str(exc)[:250]})

        def do_POST(self):
            if self.path != '/api/pdf':
                return super().do_POST()
            origin = self.headers.get('Origin')
            if origin and not self.valid_origin(origin):
                return self.reply(403, {'error': '不允许此来源'})
            try:
                size = int(self.headers.get('Content-Length', 0))
                if not 0 < size <= 42*1024*1024:
                    return self.reply(413, {'error': '请选择30MB以内的PDF。'})
                data = json.loads(self.rfile.read(size))
                source = base64.b64decode(data.get('pdf', ''), validate=True)
                if len(source) > 30*1024*1024:
                    raise ValueError('PDF不能超过30MB。')
                with fitz.open(stream=source, filetype='pdf') as doc:
                    if doc.needs_pass:
                        raise ValueError('此PDF需要密码，请先另存为未加密版本。')
                    count = len(doc)
                    if not 1 <= count <= 100:
                        raise ValueError('支持1至100页PDF，请拆分文件后上传。')
                token = secrets.token_urlsafe(24)
                (CACHE/(token+'.pdf')).write_bytes(source)
                for old in CACHE.glob('*.pdf'):
                    if time.time()-old.stat().st_mtime>86400:
                        old.unlink(missing_ok=True)
                with GUARD:
                    for key in list(DOCS):
                        if time.time()-DOCS[key][1] > 3600:
                            del DOCS[key]
                    if len(DOCS) >= 3:
                        del DOCS[min(DOCS, key=lambda k: DOCS[k][1])]
                    DOCS[token] = (source, time.time())
                self.reply(200, {'token': token, 'pages': count})
            except Exception as exc:
                self.reply(400, {'error': '无法打开PDF：'+str(exc)[:250]})
    return PDFHandler
