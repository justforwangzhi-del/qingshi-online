import {chromium} from 'playwright';
import {createServer} from 'node:http';
import {readFile,mkdir} from 'node:fs/promises';
import {resolve,extname} from 'node:path';
import {inflateRawSync} from 'node:zlib';
import assert from 'node:assert/strict';
const root=resolve('site');
const server=createServer(async(req,res)=>{try{const path=resolve(root,'.'+decodeURIComponent(new URL(req.url,'http://localhost').pathname));if(path!==root&&!path.startsWith(root+'/')&&!path.startsWith(root+'\\')){res.writeHead(403).end();return}const filePath=path===root||req.url.endsWith('/')?resolve(path,'index.html'):path;const file=await readFile(filePath);res.setHeader('Content-Type',({'.html':'text/html','.js':'text/javascript','.mjs':'text/javascript','.wasm':'application/wasm','.css':'text/css'}[extname(filePath)]||'application/octet-stream'));res.end(file)}catch{res.writeHead(404).end()}});
await new Promise(r=>server.listen(0,'127.0.0.1',r));
const url=`http://127.0.0.1:${server.address().port}/`;
let browser;
function zipEntries(buffer){const entries={};let eocd=buffer.length-22;while(eocd>=0&&buffer.readUInt32LE(eocd)!==0x06054b50)eocd--;let at=buffer.readUInt32LE(eocd+16);const count=buffer.readUInt16LE(eocd+10);for(let n=0;n<count;n++){const size=buffer.readUInt32LE(at+20),nameLen=buffer.readUInt16LE(at+28),extra=buffer.readUInt16LE(at+30),comment=buffer.readUInt16LE(at+32),offset=buffer.readUInt32LE(at+42),method=buffer.readUInt16LE(at+10);const name=buffer.subarray(at+46,at+46+nameLen).toString();const dataAt=offset+30+buffer.readUInt16LE(offset+26)+buffer.readUInt16LE(offset+28);const data=buffer.subarray(dataAt,dataAt+size);entries[name]=method===8?inflateRawSync(data):data;at+=46+nameLen+extra+comment}return entries}
try{
 browser=await chromium.launch({headless:true,...(process.env.CHROME_PATH?{executablePath:process.env.CHROME_PATH}:{})});const context=await browser.newContext({acceptDownloads:true});
 const errors=[],requests=[];
 context.on('page',p=>p.on('pageerror',e=>errors.push(e.message)));
 await context.route(/https:\/\/(api\.deepseek\.com|api\.xiaomimimo\.com)\//,async route=>{const req=route.request();requests.push({url:req.url(),body:req.postData(),auth:req.headers().authorization});if(req.url().endsWith('/models'))return route.fulfill({json:{data:[{id:'deepseek-flash'},{id:'mimo-v2.6-flash'}]}});await route.fulfill({contentType:'text/event-stream',body:'data: '+JSON.stringify({choices:[{delta:{content:'识别测试\n\n| 项目 | 数值 |\n| --- | --- |\n| A | 123 |'},finish_reason:null}]})+'\n\ndata: '+JSON.stringify({choices:[{delta:{},finish_reason:'stop'}]})+'\n\ndata: [DONE]\n\n'})});
 const page=await context.newPage();await page.goto(url);await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('请填写'));
 async function settings(key,remember){await page.click('#api-settings');if(key!==null)await page.fill('#config-key',key);await page.locator('#remember-key').setChecked(remember);await page.click('#api-form button[type=submit]');await page.click('#close-api')}
 await settings('fake-browser-key',true);await page.reload();await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('已记住'));
 const other=await context.newPage();await other.goto(url);await other.waitForFunction(()=>document.querySelector('#status').textContent.includes('已记住'));
 await page.click('#forget');await other.waitForFunction(()=>document.querySelector('#status').textContent.includes('请填写'));
 assert.equal(await page.evaluate(()=>localStorage.getItem('qingshi.browser-credentials.v1')),null);
 await settings('fake-session-key',false);await page.reload();await page.waitForFunction(()=>document.querySelector('#status').textContent.includes('请填写'));
 await settings('fake-browser-key',true);await settings(null,false);assert.equal(await page.evaluate(()=>localStorage.getItem('qingshi.browser-credentials.v1')),null);
 await page.click('#api-settings');await page.click('#test-api');await page.waitForFunction(()=>document.querySelector('#config-message').textContent.includes('连接正常'));await page.click('#close-api');
 await page.setInputFiles('#file','tests/fixtures/sample.png');await page.waitForFunction(()=>!document.querySelector('#attachment').hidden);await page.check('#cloud-consent');await page.click('#send');await page.waitForFunction(()=>document.querySelector('#progress').textContent.includes('已完成'));
 assert.match(await page.locator('#result').textContent(),/123/);
 let downloadPromise=page.waitForEvent('download');await page.click('#word');let download=await downloadPromise;let files=zipEntries(await readFile(await download.path()));assert.match(files['word/document.xml'].toString(),/123/);assert.match(files['word/document.xml'].toString(),/w:tbl/);assert.equal(Object.keys(files).filter(p=>/^word\/media\/.+\.png$/.test(p)).length,1);
 await page.setInputFiles('#file','tests/fixtures/sample.pdf');await page.waitForFunction(()=>document.querySelector('#page-total').textContent.includes('2 页'));await page.click('#send');await page.waitForFunction(()=>document.querySelector('#progress').textContent.includes('已完成 2 页'));
 downloadPromise=page.waitForEvent('download');await page.click('#word');download=await downloadPromise;files=zipEntries(await readFile(await download.path()));assert.equal(Object.keys(files).filter(p=>/^word\/media\/.+\.png$/.test(p)).length,2);assert.match(files['word/document.xml'].toString(),/第 2 页 原始页面/);
 await page.selectOption('#word-mode','original');downloadPromise=page.waitForEvent('download');await page.click('#word');download=await downloadPromise;files=zipEntries(await readFile(await download.path()));assert.ok(!files['word/document.xml'].toString().includes('识别文字'));
 await mkdir('qa',{recursive:true});await page.screenshot({path:'qa/desktop.png',fullPage:true});await page.setViewportSize({width:390,height:844});await page.screenshot({path:'qa/mobile.png',fullPage:true});assert.ok(await page.evaluate(()=>document.documentElement.scrollWidth<=innerWidth));
 assert.equal(requests.filter(r=>r.url.endsWith('/chat/completions')).length,3);assert.ok(requests.every(r=>r.auth==='Bearer fake-session-key'||r.auth==='Bearer fake-browser-key'));assert.deepEqual(errors,[]);
 console.log('PASS: remember/reload, session-only, opt-out, clear across tabs, connection test, image OCR, two-page PDF OCR, Word tables and original pages, original-only export, mobile layout');
}finally{await browser?.close();server.closeAllConnections();await new Promise(r=>server.close(r))}
