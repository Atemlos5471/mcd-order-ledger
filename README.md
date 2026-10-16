# 麦麦订单账本 · 年度回顾

> 用麦当劳官方 MCP 拉出你的真实历史订单，生成一份能发朋友圈的「麦麦年度账单」：
> Excel 多表台账 + 单文件 HTML 年度报告。

不是又一个省钱计算器。它回答的是另一个问题：**这一年，我在麦当劳到底吃了什么。**

## 它会告诉你什么

- 一年花了多少钱、客单价多少、单笔最高多少，折算成多少个巨无霸
- 月度订单趋势、你最偏爱哪个时段（早餐 / 午餐 / 下午茶 / 晚餐 / 夜宵）
- 常去门店 TOP、常点餐品 TOP、周几最容易"麦"一下
- 结合官方营养数据估算总热量摄入，并换算成需要慢跑多少公里
- 输出可直接分享的单文件 HTML 报告，以及可继续做透视的 Excel 台账（6 个 sheet）

## 快速开始

### 0. 零门槛先看效果（不需要 Token）

```bash
pip install -r requirements.txt
python src/build_report.py --demo
```

打开 `out/annual-report.html` 即可看到完整报告样式，示例数据为虚构脱敏数据。

### 1. 申请麦当劳 MCP Token

打开 [open.mcd.cn/mcp](https://open.mcd.cn/mcp) → 右上角登录（手机号验证）→ 控制台 → 激活 → 复制 MCP Token。

### 2. 配置 Token

```bash
cp .env.example .env
# 编辑 .env，填入 MCD_MCP_TOKEN=你的Token
```

`.env` 已在 `.gitignore` 中，不会被提交。

### 3. 拉取真实订单

```bash
python src/fetch_ledger.py --list-tools              # 先看看有哪些工具、各需要什么入参
python src/fetch_ledger.py --preset orders           # 拉取账单所需的四个工具
```

原始返回落在 `data/raw/`（已 gitignore，不入库）。

### 4. 生成报告

```bash
python src/build_report.py
```

产物：`out/mcd-order-ledger.xlsx`、`out/annual-report.html`。

## 数据来源

全部来自麦当劳中国官方 MCP 服务（`https://mcp.mcd.cn`，Streamable HTTP），未使用任何网页抓取或非官方接口：

| 工具 | 用途 |
|---|---|
| `order-list` | 到店 / 外送历史订单 |
| `mall-order-list` | 麦麦商城兑换与购买订单 |
| `list-nutrition-foods` | 官方餐品营养数据，用于热量估算 |
| `query-my-account` | 积分账户概览（可用/累计/即将过期） |

详细说明见 [MCP_INTEGRATION.md](./MCP_INTEGRATION.md)。

## 目录结构

```
src/
  mcd_mcp.py        MCP Streamable HTTP / JSON-RPC 客户端（会话、工具列举、工具调用）
  fetch_ledger.py   拉取订单与营养数据，落盘 data/raw/
  ledger.py         结构自适应解析 + 统计分析（不假设固定字段名）
  build_report.py   Excel 台账 + HTML 报告生成
examples/
  sample_orders.json  虚构脱敏示例数据，供 --demo 使用
```

## 为什么是"结构自适应"解析

麦当劳 MCP 各工具的返回字段命名并不统一，且会随版本演进。这里没有硬编码字段名，
而是递归扫描 JSON，找出最像订单的那批记录，再按关键词匹配时间、金额、门店、餐品字段。
好处是 MCP 升级后大概率仍然能跑；代价是极端结构下可能解析不出，此时用
`--list-tools` 确认返回结构即可。

## 目标用户

- 想知道自己在麦当劳真实消费画像的人
- 想用官方 MCP 做数据分析、而不是再做一遍省钱计算的开发者
- 需要一份 MCP + Streamable HTTP + 数据可视化完整参考实现的同学

## 隐私

- Token 只从环境变量读取，从不写入任何产出文件
- `data/raw/`（含真实订单）默认 gitignore，不会上传
- 提交的配置示例 `mcp-config.example.json` 只含 `${MCD_MCP_TOKEN}` 占位符

## 参赛信息

麦当劳程序员创意开发大赛（1024 程序员节）参赛作品，用 WorkBuddy 开发。
本项目为参赛者独立开发，非麦当劳官方产品；餐品信息、价格与供应状态以麦当劳官方渠道实时结果为准。
