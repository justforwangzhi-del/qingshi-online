# 轻识 · 在线版

轻量的在线图片 / PDF 文档识别工具，保留原版界面，使用 DeepSeek 或小米 MiMo 云端 API。无需 Ollama、显卡或本地 OCR 模型。

## 功能

- 上传、拖拽、粘贴 PNG / JPG / WebP，图片最大 15MB / 2500 万像素。
- PDF 最大 30MB / 100 页，指定页码逐页识别。
- 文字识别、表格提取、自定义要求，实时显示输出，可停止任务。
- 复制文字、下载 Markdown、导出包含原始页面的 Word，保留原件中的签名及印章。
- API 密钥只放在服务器环境变量中，页面仅返回配置状态。
- 全站访问口令验证；临时 PDF / Word 每 5 分钟清理超过 24 小时的文件。重启可能提前清除临时文件。

## 部署到 Render

仓库内含 `render.yaml`。在 Render 中选择 **New → Blueprint**，连接此 GitHub 仓库。

1. 填写 `DEEPSEEK_API_KEY` 或 `MIMO_API_KEY`，至少配置一个；未使用的平台留空。
2. 部署完成后，在服务 Environment 中查看自动生成的 `ACCESS_PASSWORD`。
3. 打开 Render 提供的 HTTPS 地址，用户名默认 `qingshi`，密码为上述值。
4. 可选：将 `PUBLIC_URL` 设置为实际访问地址（例如 `https://qingshi-online.onrender.com`，末尾不加 `/`）。绑定域名后同步修改。

平台的服务器费用和模型 API 费用由对应账号承担。模型列表可连接不代表图片输入一定可用，请用一张不含敏感信息的图片验证权限和额度。

Render 配置依据：[Blueprint 规范](https://render.com/docs/blueprint-spec)、[环境变量设置](https://render.com/docs/configure-environment-variables)。

## 部署到自己的服务器

需要 Docker Compose，以及指向服务器的域名。建议通过 Caddy / Nginx 提供 HTTPS。

```sh
git clone https://github.com/justforwangzhi-del/qingshi-online.git
cd qingshi-online
cp .env.example .env
# 编辑 .env：设置访问密码、真实域名和至少一个平台 API 密钥
docker compose up -d --build
```

容器端口默认只绑定服务器本机 `127.0.0.1:8787`，由反向代理对外提供 HTTPS。Caddy 示例：

```caddy
ocr.example.com {
    reverse_proxy 127.0.0.1:8787
}
```

Nginx 反向代理需要允许大请求并关闭流式响应缓冲：

```nginx
location / {
    proxy_pass http://127.0.0.1:8787;
    client_max_body_size 45m;
    proxy_read_timeout 360s;
    proxy_buffering off;
    proxy_set_header Host $host;
    proxy_set_header X-Forwarded-Proto $scheme;
}
```

## 环境变量

| 变量 | 说明 |
| --- | --- |
| `ACCESS_PASSWORD` | 必填。访问密码；未配置时服务拒绝启动。请替换示例值。 |
| `ACCESS_USERNAME` | 访问用户名，默认 `qingshi`。建议使用英文和数字。 |
| `PUBLIC_URL` | 对外访问源地址，含协议及非标准端口，不含路径。用于校验网页请求来源；不设置时按 Host 校验。 |
| `DEEPSEEK_API_KEY` | DeepSeek 密钥。 |
| `DEEPSEEK_MODEL` | 默认 `deepseek-flash`，需要具备图片输入权限。 |
| `DEEPSEEK_BASE_URL` | 默认 `https://api.deepseek.com`，仅支持官方地址。 |
| `MIMO_API_KEY` | 小米 MiMo 密钥。 |
| `MIMO_MODEL` | 默认 `mimo-v2.6-flash`，需要具备图片输入权限。 |
| `MIMO_BASE_URL` | 默认 `https://api.xiaomimimo.com/v1`，也支持官方 Token Plan 地址 `https://token-plan-cn.xiaomimimo.com/v1`。 |
| `PORT` | 默认 `8787`；托管平台可自动覆盖。Compose 内保持 8787。 |

密钥不要写入代码、网页、提交记录或构建参数，`.env` 已加入忽略文件。

## 本地验证

```sh
python -m venv .venv
# Linux/macOS
. .venv/bin/activate
# Windows PowerShell: .\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
# 设置环境变量 ACCESS_PASSWORD 和所需 API 密钥后运行
python server.py
```

打开 `http://127.0.0.1:8787`。直接运行 Python 不会自动读取 `.env`；Docker Compose 会读取。

运行检查：`python -m unittest discover -s tests -v`。

## 使用范围

此版本适用于个人或可信小组共享同一访问账号，识别请求串行处理。知道访问口令的人会共享 API 额度和临时文件访问权限；不包含独立用户、额度分配或计费系统。请通过 HTTPS 使用。

PDF 上传本站后渲染为图片，所选页面会发送到选中的模型平台。Word 在本站服务器生成。临时文件不作为长期存储；容器销毁或服务器重启后，导出任务可能需要重做。浏览器关闭或停止识别后，上游已经接收的请求仍可能计费。

GitHub 保存代码，本项目需要运行 Python / Docker 的服务器，不能直接通过 GitHub Pages 执行。

接口资料：[DeepSeek 图片输入](https://api-docs.deepseek.com/guides/vision/)、[MiMo 图片理解](https://mimo.mi.com/docs/usage-guide/multimodal-understanding/image-understanding)。
