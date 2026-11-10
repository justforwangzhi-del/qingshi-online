import os
import http.client
import json
import re
import threading
from urllib.parse import urlsplit

CONFIG_LOCK=threading.Lock()
CONFIGS={
    'deepseek':{'base':'https://api.deepseek.com','model':'deepseek-flash','key':''},
    'mimo':{'base':'https://api.xiaomimimo.com/v1','model':'mimo-v2.6-flash','key':''}
}
ALLOWED={'deepseek':{'https://api.deepseek.com','https://api.deepseek.com/v1'},
         'mimo':{'https://api.xiaomimimo.com/v1','https://token-plan-cn.xiaomimimo.com/v1'}}

for provider, config in CONFIGS.items():
    prefix = provider.upper()
    config['key'] = os.environ.get(prefix+'_API_KEY', '').strip()
    config['base'] = os.environ.get(prefix+'_BASE_URL', config['base']).rstrip('/')
    config['model'] = os.environ.get(prefix+'_MODEL', config['model'])
    if config['base'] not in ALLOWED[provider]:
        raise ValueError(prefix+'_BASE_URL 必须是支持的官方接口地址')

def public_config():
    with CONFIG_LOCK:return {p:{'base':v['base'],'model':v['model'],'has_key':bool(v['key'])} for p,v in CONFIGS.items()}

def get_config(provider):
    with CONFIG_LOCK:config=dict(CONFIGS.get(provider,{}))
    if not config:raise ValueError('不支持此模型服务。')
    if not config['key']:raise ValueError('管理员尚未配置此平台的 API 密钥。')
    return config

def connect(config,timeout=300):
    url=urlsplit(config['base'])
    return http.client.HTTPSConnection(url.hostname,timeout=timeout),url.path.rstrip('/')

def headers(config):
    return {'Content-Type':'application/json','Authorization':'Bearer '+config['key'], 'api-key':config['key']}

def safe_error(status):
    return {401:'API密钥无效，请检查密钥与平台是否匹配。',403:'账号没有访问该模型的权限。',402:'账号余额或额度不足。',404:'模型或接口不存在，请核对模型名称和API地址。',429:'请求过于频繁或额度受限，请稍后重试。',400:'请求未被接受，请确认模型支持图片输入，并核对模型名称。'}.get(status,'平台返回错误（HTTP '+str(status)+'），请稍后重试。')

def sse_events(response):
    parts=[]
    while True:
        line=response.readline()
        if not line:
            if parts:yield '\n'.join(parts)
            return
        line=line.decode('utf-8').rstrip('\r\n')
        if not line:
            if parts:yield '\n'.join(parts);parts=[]
        elif line.startswith('data:'):parts.append(line[5:].lstrip())

def cloud_ocr(handler,data,decoded,prompt,lock):
    try:
        config=get_config(data.get('provider'))
        if data.get('cloud_consent') is not True:raise ValueError('请先确认允许将本次图片或PDF页面发送到所选平台。')
    except ValueError as exc:return handler.reply(400,{'error':str(exc)})
    if not lock.acquire(blocking=False):return handler.reply(409,{'error':'另一个识别任务正在进行，请稍后重试。'})
    conn,path=connect(config);started=False
    try:
        mime='image/png' if decoded.startswith(b'\x89PNG') else ('image/jpeg' if decoded.startswith(b'\xff\xd8') else 'image/webp')
        payload={'model':config['model'],'messages':[{'role':'user','content':[{'type':'image_url','image_url':{'url':f'data:{mime};base64,'+data['image']}},{'type':'text','text':prompt}]}], 'stream':True,'max_completion_tokens':8192}
        if data.get('provider')=='deepseek':
            payload['max_tokens']=payload.pop('max_completion_tokens')
            payload['thinking']={'type':'disabled'}
        conn.request('POST',path+'/chat/completions',json.dumps(payload),headers(config))
        response=conn.getresponse()
        if response.status!=200:
            response.read();return handler.reply(502,{'error':safe_error(response.status)})
        handler.send_response(200);handler.send_header('Content-Type','application/x-ndjson; charset=utf-8');handler.send_header('Cache-Control','no-store');handler.send_header('Connection','close');handler.end_headers();handler.close_connection=True;started=True
        def send(item):handler.wfile.write((json.dumps(item,ensure_ascii=False)+'\n').encode());handler.wfile.flush()
        finished=False
        for event in sse_events(response):
            if event=='[DONE]':break
            item=json.loads(event)
            if item.get('error'):raise ValueError('平台处理失败，请核对模型支持的输入类型。')
            for choice in item.get('choices',[]):
                content=choice.get('delta',{}).get('content')
                if isinstance(content,str) and content:send({'response':content,'done':False})
                reason=choice.get('finish_reason')
                if reason:
                    if reason not in ('stop','length'):raise ValueError('平台未完整返回结果（'+str(reason)[:40]+'）。')
                    send({'done':True,'done_reason':reason});finished=True
        if not finished:raise ValueError('云端连接提前结束，结果可能不完整，请重试。')
    except (BrokenPipeError,ConnectionResetError):pass
    except Exception as exc:
        msg=str(exc) if isinstance(exc,ValueError) else '连接云端失败或超时，请检查网络后重试。'
        if started:
            try:send({'error':msg})
            except OSError:pass
        else:handler.reply(502,{'error':msg})
    finally:conn.close();lock.release()

