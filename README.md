# 轻识 · GitHub Pages 在线版

直接打开网页，使用自己的 DeepSeek / MiMo API 密钥识别图片和 PDF。无需 Render、Python 服务、Ollama 或本地 OCR。

## 密钥使用

点击 **API 设置**，选择平台、填写模型及密钥，保存后即可使用。

- 默认仅在当前页面内存中使用，刷新或关闭页面后需要重新填写。
- 勾选 **记住密钥，下次自动读取** 后，密钥保存在当前浏览器的 localStorage 中。
- 取消勾选并保存，会删除该平台的持久密钥，仅保留本次使用。
- 点击顶部 **清除密钥**，删除两个平台的已保存密钥和当前页面内存中的密钥；其他打开的本站页面也会同步清除或重新读取。
- 隐私模式、清理网站数据或更换浏览器后需要重新填写。若浏览器阻止存储，会提示退回本次使用。

密钥不会写入 GitHub 代码或上传本站后端，浏览器仅将密钥发送给选中的官方模型 API。浏览器存储不是加密保险箱；共用电脑建议不记住。GitHub Pages 同一个域名下的项目共用浏览器来源，仅在信任的个人 Pages 域名中记住密钥。

## 功能与数据流

支持图片上传、拖拽、粘贴截图（PNG / JPG / WebP，15MB、2500万像素以内），PDF 最多30MB / 100页、指定页码逐页识别，文字识别、表格提取、自定义要求，实时输出和停止任务。

PDF 由浏览器中的 PDF.js 渲染；仅所选页面发送到模型平台。支持复制、下载 Markdown，以及浏览器内生成 Word（文字与原件 / 仅原件，原图保留签名印章）。文件和识别结果不会保存到 GitHub。刷新页面后需要重新上传文件。

平台需要支持图片输入并有相应权限、额度。测试连接只检查密钥与模型列表，不代表图片输入已验证。停止任务后，上游已接收的请求仍可能计费。

浏览器跨域访问受平台策略及网络影响。目前官方接口预检允许直接调用；如平台策略变化，页面会提示连接问题，可切换另一官方地址或平台。不要关闭浏览器安全设置。

## GitHub Pages 发布

页面全部位于 `site/`；`.github/workflows/pages.yml` 会发布这个目录。

1. 打开仓库 Settings → Pages，将 Source 设为 GitHub Actions。
2. 推送 main，或手动运行 GitHub Pages 工作流。
3. 部署后的地址为 https://justforwangzhi-del.github.io/qingshi-online/ 。

GitHub Free 需要公开仓库才能使用 Pages。私有仓库需账号套餐支持。页面本身会公开，访问者填写自己的密钥。

## 本地预览和测试

```sh
python -m http.server 8080 --directory site
# 打开 http://localhost:8080，不要直接双击 HTML 文件
npm ci
npm test
npx playwright install chromium
npm run test:browser
```

自动检查覆盖密钥记住/恢复/取消/清除、接口地址限制、流式解析，以及浏览器内图片、PDF 与 Word 导出。识别请求用模拟接口测试，不消耗真实额度。

依赖组件随网页发布，不从外部 CDN 加载代码。版本与许可证见 `site/THIRD_PARTY.md`。

资料：[GitHub Pages](https://docs.github.com/en/pages/getting-started-with-github-pages/what-is-github-pages)、[PDF.js](https://mozilla.github.io/pdf.js/examples/)、[docx](https://docx.js.org/api/classes/index.Packer.html)、[DeepSeek 图片输入](https://api-docs.deepseek.com/guides/vision/)、[MiMo 图片理解](https://mimo.mi.com/docs/usage-guide/multimodal-understanding/image-understanding)。
