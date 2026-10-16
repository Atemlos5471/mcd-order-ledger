# MCP 集成说明

## 1. 使用的 MCP Server

| 项 | 值 |
|---|---|
| Server | 麦当劳中国 MCP 服务 |
| 接入地址 | `https://mcp.mcd.cn` |
| 传输协议 | Streamable HTTP（JSON-RPC 2.0） |
| 鉴权 | 请求头 `Authorization: Bearer ${MCD_MCP_TOKEN}` |
| 限流 | 600 次 / 分钟（超限返回 429） |
| 官方文档 | https://github.com/M-China/mcd-mcp-server |

配置示例（已脱敏，仅保留环境变量占位符）见 `mcp-config.example.json`：

```json
{
  "mcpServers": {
    "mcd-mcp": {
      "type": "streamablehttp",
      "url": "https://mcp.mcd.cn",
      "headers": { "Authorization": "Bearer ${MCD_MCP_TOKEN}" }
    }
  }
}
```

## 2. 实际调用的 Tools

| Tool | 在本项目中的作用 | 业务价值 |
|---|---|---|
| `order-list` | 拉取近期到店 / 外送历史订单 | 账单主体数据：金额、时间、门店、餐品明细 |
| `mall-order-list` | 拉取麦麦商城近一年兑换 / 购买订单 | 补全积分兑换侧支出，避免账单只覆盖点餐 |
| `list-nutrition-foods` | 获取官方餐品营养成分 | 把消费金额换算成热量摄入，产出健康视角结论 |
| `query-my-account` | 查询积分账户（可用 / 累计 / 冻结 / 即将过期） | 积分资产概览，提示即将过期积分 |

可通过 `python src/fetch_ledger.py --list-tools` 实时列出服务端的全部工具及其入参 schema，
本项目不硬编码工具清单，服务端新增工具后可直接被列出和调用。

## 3. 调用流程

```
McpClient.initialize()                 # JSON-RPC initialize，记录 Mcp-Session-Id
        │
        ├─ notifications/initialized   # 单向通知，不期待响应
        │
        ├─ tools/list                  # 可选：确认可用工具与入参 schema
        │
        └─ tools/call × N              # order-list / mall-order-list / ...
                │
                ├─ 解析响应              # 自动兼容 application/json 与 text/event-stream(SSE)
                ├─ 落盘 data/raw/*.json
                │
                └─ ledger.normalize_orders()  →  结构自适应解析成订单
                        │
                        └─ summarize()  →  build_report.py  →  xlsx + html
```

协议层实现要点（`src/mcd_mcp.py`）：

- MCP Streamable HTTP 要求客户端同时声明 `Accept: application/json, text/event-stream`，
  服务端可任选其一返回，因此响应解码需同时支持普通 JSON 与 SSE（`data:` 行）。
- 服务端可能下发 `Mcp-Session-Id` 响应头，客户端需在后续请求中回传，否则会 400。
- `notifications/initialized` 是单向通知，发送后不应等待响应体。
- `tools/call` 的返回优先取 `structuredContent`；缺失时尝试对 `content[0].text` 做 JSON 解析。
- 401 / 429 单独识别并给出可操作提示（Token 无效 / 触发限流）。

## 4. 业务价值

麦当劳 MCP 已开放点餐、优惠券、积分、商城、团餐、派对等 30+ 工具，
但已公开的作品大多集中在"下单前"的省钱计算。

本项目把 MCP 当作**数据出口**而非下单入口：用官方订单与营养数据回看真实消费行为，
产出个人年度报告。这条路径的价值在于：

1. 数据全部来自官方接口，不存在抓取合规问题；
2. 订单是高频、连续、结构化的真实数据，天然适合做时间序列与画像分析；
3. 年度报告形态自带传播属性，是 MCP 能力面向普通用户最容易理解的表达方式。
