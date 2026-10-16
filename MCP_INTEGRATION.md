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
| `order-list` | 拉取历史订单列表（无入参，返回全量） | 账单主体：时间、门店、餐品、订单状态 |
| `query-order` | 按 orderId 逐单查详情 | **关键**：唯一能拿到商品原价 `productPrice`、优惠券明细 `couponList`、就餐方式 `takeWay` 的工具 |
| `mall-order-list` | 拉取麦麦商城近一年兑换 / 购买订单 | 补全积分兑换侧支出，避免账单只覆盖点餐 |
| `list-nutrition-foods` | 获取官方餐品营养成分 | 把消费金额换算成热量摄入，产出健康视角结论 |
| `query-my-account` | 查询麦享会积分账户（可用 / 累计 / 冻结 / 即将过期） | 积分资产概览，提示即将过期积分 |

可通过 `python src/fetch_ledger.py --list-tools` 实时列出服务端的全部工具及其入参 schema
（当前 35 个），本项目不硬编码工具清单，服务端新增工具后可直接被列出和调用。

### 金额口径（踩过的坑）

`order-list` 与 `query-order` 返回的 `totalAmount` / `realTotalAmount` 在优惠券全额抵扣时
均为 `"0"`，不能直接当作实付。实测一条"麦香鸡三件套（原价 ¥39.5）用券全额抵扣"的订单：

```json
"totalAmount": "0",
"realTotalAmount": "0",
"totalDiscountAmount": "0",
"productPrice": "39.5",
"couponList": [{ "couponName": "麦香鸡三件套", "discountAmount": "39.5" }]
```

因此本项目以 `productPrice` 为原价主口径，实付取 `realTotalAmount`，
节省 = 原价 − 实付，并在报告页脚明确标注口径。这也让报告的核心结论从
"花了多少钱"变成"麦当劳请了你多少顿"。

## 3. 调用流程

```
fetch_ledger.py --preset orders
    McpClient.initialize()            # JSON-RPC initialize，记录 Mcp-Session-Id
        ├─ notifications/initialized # 单向通知，不期待响应
        └─ tools/call × 4             # order-list / mall-order-list /
                                      # list-nutrition-foods / query-my-account
                └─ 落盘 data/raw/

enrich_orders.py
    └─ 对每笔 orderId 调 tools/call query-order
        └─ 合并 productPrice / couponList / takeWay / storeAddress
            └─ 落盘 data/raw/order-list-enriched.json

build_report.py
    ledger.normalize_orders()  →  结构自适应解析成订单
        └─ summarize()  →  xlsx 十表台账 + 单文件 HTML 报告
```

协议层实现要点（`src/mcd_mcp.py`）：

- MCP Streamable HTTP 要求客户端同时声明 `Accept: application/json, text/event-stream`，
  服务端可任选其一返回，因此响应解码需同时支持普通 JSON 与 SSE（`data:` 行）。
- 服务端可能下发 `Mcp-Session-Id` 响应头，客户端需在后续请求中回传。
- `notifications/initialized` 是单向通知，发送后不应等待响应体。
- `tools/call` 的返回优先取 `structuredContent`；缺失时尝试对 `content[0].text` 做 JSON 解析。
- 401 / 429 单独识别并给出可操作提示（Token 无效 / 触发 600 次每分钟限流）。
- MCP Token 由用户在开放平台控制台自行申请，客户端只做 Bearer 透传，从不落盘到产出文件。

## 4. 业务价值

麦当劳 MCP 已开放点餐、优惠券、积分、商城、团餐、派对等 30+ 工具，
但已公开的作品大多集中在"下单前"的省钱计算。

本项目把 MCP 当作**数据出口**而非下单入口：用官方订单与营养数据回看真实消费行为，
产出个人年度报告。这条路径的价值在于：

1. 数据全部来自官方接口，不存在抓取合规问题；
2. 订单是高频、连续、结构化的真实数据，天然适合做时间序列与画像分析；
3. 年度报告形态自带传播属性，是 MCP 能力面向普通用户最容易理解的表达方式。
