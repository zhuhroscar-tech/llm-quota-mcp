# llm-quota-mcp

[![English](https://img.shields.io/badge/English-555555?style=flat)](README.md) [![简体中文](https://img.shields.io/badge/简体中文-555555?style=flat)](README.zh-CN.md)

通过 CLI、Python API 或 stdio MCP server，查看 LLM API 返回的速率限制信息，以及 Hermes Agent 本地记录的用量。它**不是月度余额或订阅额度查询工具**；无法获取的字段保留为 `None` / `null`，并附带说明。

![额度报告示例](docs/images/example-output.png)

## 能读取什么

- **Anthropic：**通过 `count_tokens` 探测请求读取返回的 rate-limit headers。该请求不生成付费 completion，但响应可能不含相关 headers。
- **OpenAI：**发起最小 chat completion，读取请求数/token 窗口。这是真实 API 调用，会产生少量 token 费用。可选的组织 Admin API key 用于查询历史用量和费用，普通 project key 不具备该权限。
- **Hermes：**通过 `hermes sessions export` 读取本地 token 和费用记录，表示已发生的用量，而非服务商剩余额度。

## 安装

需要 Python 3.10+。服务商探测使用 `requests`，MCP extra 会安装 MCP SDK；Hermes 读取功能还要求 PATH 中有兼容的 `hermes` 命令。

```bash
git clone https://github.com/zhuhroscar-tech/llm-quota-mcp.git
cd llm-quota-mcp
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[mcp]"
llm-quota --help
```

只用 CLI 时可改为 `pip install -e .`。

## CLI 与 Python

通过本地密钥管理环境提供 `ANTHROPIC_API_KEY` 或 `OPENAI_API_KEY`。OpenAI 可选设置为 `OPENAI_ADMIN_API_KEY` 和 `OPENAI_ORG_ID`。

```bash
llm-quota anthropic --json
llm-quota openai --json
llm-quota hermes --newer-than 24h --json
```

用 `--model` 选择当前 key 有权访问的模型。网络错误、认证失败或模型不支持探测请求，都可能导致无法生成报告。

```python
import os
from llm_quota import get_anthropic_quota

quota = get_anthropic_quota(api_key=os.environ["ANTHROPIC_API_KEY"])
print(quota.requests.remaining, quota.requests.reset_at)
```

## MCP 接入

在宿主中将 `llm-quota-mcp` 注册为 **stdio** server。采用 `mcpServers` 配置格式的宿主可参考：

```json
{
  "mcpServers": {
    "llm-quota": {"command": "/absolute/path/to/.venv/bin/llm-quota-mcp"}
  }
}
```

替换为实际可执行文件路径，再通过宿主提供的环境变量或密钥机制向 server 进程传入凭据；不同宿主的配置格式并不相同。提供的工具为 `check_anthropic_quota`、`check_openai_quota`、`check_hermes_usage`。

## 安全与测试

不要提交 key，也不要把 key 粘贴到 agent 对话中。优先使用环境变量，而不是每次调用时传入密钥；仅在确有需要时授予 Admin API 权限。结果可能包含敏感用量及费用信息。速率窗口只是当前快照，不保证之后的请求一定成功。

```bash
pip install -e ".[dev]"
pytest -v
```

服务商测试使用模拟 HTTP，不能据此认定真实账户行为已验证；Hermes 集成测试取决于是否存在兼容 CLI。[MIT 许可证](LICENSE)。
