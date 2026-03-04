# TmpAPI

浏览器 RPA 伪装的 OpenAI 格式 API 工具。

通过 Playwright 操控模型官网，将网页聊天接口封装为 OpenAI Chat Completions API 格式，在本地提供服务。

目前支持的 Provider：

| Provider | 官网 | 模型 ID |
|----------|------|---------|
| DeepSeek | chat.deepseek.com | `deepseek-chat`、`deepseek-reasoner` |
| 智谱清言 | chatglm.cn | `glm-5` | # 暂时不可用
| 豆包 AI | www.doubao.com | `doubao` |

## 快速开始

### 1. 安装依赖

```bash
uv sync
```

> 无需单独下载 Chromium，工具会直接使用系统已安装的 Chrome 或 Edge 浏览器。
> Windows 系统自带 Edge，开箱即用。

### 2. 登录

首次使用需要先登录，工具会指导你打开浏览器让你手动完成登录：

```bash
uv run tmpapi login
```

如需指定 Provider：

可以在config.yaml中修改 Provider

也可以直接用cli传入

```bash
uv run tmpapi login --provider deepseek
uv run tmpapi login --provider chatglm
uv run tmpapi login --provider doubao
```

登录完成后关闭浏览器窗口，会话将自动保存。

### 3. 启动服务

```bash
uv run tmpapi server
```

切换不同 Provider， 可以在config.yaml中修改 Provider

也可以直接用cli传入

```bash
uv run tmpapi server --port 8686 --provider deepseek
uv run tmpapi server --port 8686 --provider chatglm
uv run tmpapi server --port 8686 --provider doubao
```

### 4. 使用

可以先尝试运行langchain demo测试样例：

```bash
uv run python tests/langchain_demo.py
```

配置任意 OpenAI SDK 客户端（模型名会自动适配当前 Provider）：

```python
from openai import OpenAI

client = OpenAI(
    base_url="http://localhost:8686/v1",
    api_key="not-needed",
)

response = client.chat.completions.create(
    model="deepseek-chat",  # 或 glm-5、doubao，取决于当前 Provider
    messages=[{"role": "user", "content": "你好"}],
)
print(response.choices[0].message.content)
```

## CLI 命令

```bash
# 登录（打开浏览器手动登录）
uv run tmpapi login --provider deepseek

# 启动 API 服务（无头模式）
uv run tmpapi server --port 8686

# 启动 API 服务（有头模式，方便调试）
uv run tmpapi server --port 8686 --no-headless

# 指定浏览器（chrome / msedge / auto）
uv run tmpapi server --port 8686 --channel chrome

# 查看帮助
uv run tmpapi --help
```

## 配置

编辑项目根目录的 `config.yaml` 切换 Provider 和调整参数：

```yaml
provider:
  name: "deepseek"   # deepseek / chatglm / doubao
```

每个 Provider 有独立的配置节，支持设置轮询间隔、超时、模拟输入速度等。

## API 端点

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/v1/models` | 列出可用模型 |
| POST | `/v1/chat/completions` | 聊天补全（支持 streaming） |
| GET | `/health` | 健康检查 |

## 扩展新 Provider

1. 在 `src/tmpapi/providers/` 下创建新文件
2. 继承 `ChatProvider` 基类并实现所有抽象方法
3. 在 `src/tmpapi/config.py` 的 `_register_builtins()` 中注册

## 技术栈

- Python 3.13+ / uv
- Playwright（浏览器自动化）
- FastAPI + uvicorn（HTTP 服务）
- SSE-Starlette（Server-Sent Events 流式响应）
