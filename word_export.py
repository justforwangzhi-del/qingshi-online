import base64
import io
import json
import re
import time
import secrets
import threading
import traceback
from pathlib import Path
from urllib.parse import urlsplit, parse_qs
from docx import Document
from docx.shared import Cm, Pt, RGBColor
from docx.oxml import OxmlElement
from docx.oxml.ns import qn
from docx.enum.text import WD_ALIGN_PARAGRAPH
import fitz
from pdf_support import load_source
EXPORTS=Path(__file__).parent/'exports'
EXPORTS.mkdir(exist_ok=True)
JOBS={}
JOB_LOCK=threading.Lock()
BUILD_LOCK=threading.Lock()

def markdown(doc, text):
    lines=text.splitlines(); i=0
    while i<len(lines):
        line=lines[i].strip(); i+=1
        line=re.sub(r'^<md>\s*','',line).replace('</md>','')
        if not line: continue
        if line.startswith('|') and i<len(lines) and re.match(r'^\|?[\s:|\-]+\|?$',lines[i].strip()):
            rows=[[c.strip() for c in line.strip('|').split('|')]]; i+=1
            while i<len(lines) and lines[i].strip().startswith('|'):
                rows.append([c.strip() for c in lines[i].strip().strip('|').split('|')]);i+=1
            cols=max(map(len,rows))
            if cols>20:
                doc.add_paragraph('\n'.join(' | '.join(r) for r in rows));continue
            table=doc.add_table(rows=0,cols=cols)
            table.style='Table Grid'
            for n,row in enumerate(rows):
                cells=table.add_row().cells
                for j,value in enumerate(row):
                    cells[j].text=value
                    for p in cells[j].paragraphs:
                        for run in p.runs: run.font.size=Pt(9);run.bold=n==0
                if n==0:
                    mark=OxmlElement('w:tblHeader');table.rows[0]._tr.get_or_add_trPr().append(mark)
            doc.add_paragraph();continue
        heading=re.match(r'^(#{1,6})\s+(.+)',line)
        if heading: doc.add_heading(heading[2],min(len(heading[1]),3));continue
        if line in ('---','***','```','```markdown'):continue
        paragraph=doc.add_paragraph()
        for n,part in enumerate(re.split(r'\*\*(.+?)\*\*',line)):
            paragraph.add_run(part).bold=bool(n%2)

def make_word(data):
    pages=data.get('pages',[])
    if not isinstance(pages,list) or not 1<=len(pages)<=100:raise ValueError('没有可导出的页面，请先识别。')
    token=data.get('token'); source=None
    if token:
        source=load_source(token)
    original_only=data.get('mode')=='original'
    doc=Document(); sec=doc.sections[0]
    sec.page_width=Cm(21);sec.page_height=Cm(29.7)
    sec.top_margin=sec.bottom_margin=Cm(1.8);sec.left_margin=sec.right_margin=Cm(1.8)
    for name in ['Normal','Title','Heading 1','Heading 2','Heading 3']:
        style=doc.styles[name];style.font.name='Microsoft YaHei';style._element.get_or_add_rPr().rFonts.set(qn('w:eastAsia'),'Microsoft YaHei');style.font.color.rgb=RGBColor(0,0,0)
        style.font.size=Pt(10.5 if name=='Normal' else 14)
        style.paragraph_format.space_after=Pt(6)
    for index,record in enumerate(pages):
        page_no=int(record.get('page',1))
        if index:doc.add_page_break()
        if not original_only:
            doc.add_heading(f'第 {page_no} 页 识别文字',1)
            text=str(record.get('text',''))[:200000]
            markdown(doc,text or '本页没有返回可识别文字。')
            doc.add_page_break()
        doc.add_heading(f'第 {page_no} 页 原始页面',1)
        if source:
            with fitz.open(stream=source,filetype='pdf') as pdf:
                if not 1<=page_no<=len(pdf):raise ValueError('导出页码无效。')
                page=pdf[page_no-1];scale=2400/max(page.rect.width,page.rect.height)
                pic=page.get_pixmap(matrix=fitz.Matrix(scale,scale),alpha=False).tobytes('png')
        else:
            pic=base64.b64decode(data.get('image',''),validate=True)
        # Preserve the complete page including seals and signatures, without relocating them.
        from PIL import Image
        with Image.open(io.BytesIO(pic)) as image:w,h=image.size
        width=min(17.4,23*h**-1*w)
        p=doc.add_paragraph();p.alignment=WD_ALIGN_PARAGRAPH.CENTER
        shape=p.add_run().add_picture(io.BytesIO(pic),width=Cm(width))
        shape._inline.docPr.set('descr',f'第{page_no}页原始页面 包含原有签名和印章')
    output=io.BytesIO();doc.save(output);return output.getvalue()

def word_handler(Base):
    class WordHandler(Base):
        def do_GET(self):
            parsed=urlsplit(self.path)
            if parsed.path not in ('/api/word-status','/api/word-download'):
                return super().do_GET()
            job_id=parse_qs(parsed.query).get('id',[''])[0]
            with JOB_LOCK:job=JOBS.get(job_id)
            if not job:return self.reply(404,{'error':'导出任务不存在，请重新导出。'})
            if parsed.path=='/api/word-status':return self.reply(200,{'state':job['state'],'error':job.get('error'),'url':'/api/word-download?id='+job_id})
            if job['state']!='done':return self.reply(409,{'error':'文件尚未生成完成。'})
            path=EXPORTS/(job_id+'.docx')
            self.send_response(200)
            self.send_header('Content-Type','application/vnd.openxmlformats-officedocument.wordprocessingml.document')
            self.send_header('Content-Disposition',"attachment; filename=ocr-result.docx; filename*=UTF-8''"+__import__('urllib.parse',fromlist=['quote']).quote(job['name']))
            self.send_header('Content-Length',str(path.stat().st_size))
            self.send_header('Cache-Control','no-store')
            self.send_header('Connection','close')
            self.end_headers();self.close_connection=True
            try:
                with path.open('rb') as source:
                    while chunk:=source.read(65536):self.wfile.write(chunk)
            except (BrokenPipeError,ConnectionResetError):pass

        def do_POST(self):
            if self.path!='/api/export-word':return super().do_POST()
            origin=self.headers.get('Origin')
            if origin and not self.valid_origin(origin):return self.reply(403,{'error':'不允许此来源'})
            try:
                length=int(self.headers.get('Content-Length',0))
                if not 0<length<=30*1024*1024:return self.reply(413,{'error':'导出内容过大，请分段识别后导出。'})
                data=json.loads(self.rfile.read(length))
                if not isinstance(data.get('pages'),list) or not data['pages']:raise ValueError('请先识别文档。')
                if not BUILD_LOCK.acquire(blocking=False):return self.reply(409,{'error':'正在生成另一份Word，请稍后重试。'})
                job_id=secrets.token_urlsafe(24)
                name=re.sub(r'[\x00-\x1f/\\]','_',str(data.get('name','识别结果')))[:120]
                name=re.sub(r'\.[^.]+$','',name)+'_识别结果.docx'
                with JOB_LOCK:
                    for key in list(JOBS):
                        if time.time()-JOBS[key]['created']>86400:
                            (EXPORTS/(key+'.docx')).unlink(missing_ok=True);del JOBS[key]
                    JOBS[job_id]={'state':'building','name':name,'created':time.time()}
                def build():
                    try:
                        result=make_word(data)
                        (EXPORTS/(job_id+'.docx')).write_bytes(result)
                        with JOB_LOCK:JOBS[job_id]['state']='done'
                    except Exception as exc:
                        traceback.print_exc()
                        with JOB_LOCK:JOBS[job_id].update(state='error',error='Word生成失败：'+str(exc)[:250])
                    finally:BUILD_LOCK.release()
                threading.Thread(target=build,daemon=True).start()
                self.reply(202,{'id':job_id})
            except Exception as exc:self.reply(400,{'error':'Word导出失败：'+str(exc)[:250]})
    return WordHandler
