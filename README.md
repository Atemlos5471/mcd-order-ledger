# 麦麦订单账本 · 年度回顾

> 用麦当劳官方 MCP 拉出你的真实历史订单，生成一份能发朋友圈的「麦麦年度账单」：
> Excel 多表台账 + 单文件 HTML 年度报告。

不是又一个省钱计算器。它回答的是另一个问题：**这一年，麦当劳到底请了你多少顿。**

原价取自订单详情接口，实付金额被优惠券全额抵扣时显示为 0——所以报告的第一屏不是
"你花了多少钱"，而是"**麦当劳替你出了多少**"。

## 在线预览

不用装环境，先看效果：

| 数据 | 说明 |
|---|---|
| [真实数据预览（门店已脱敏）](https://atemlos5471.github.io/mcd-order-ledger/report-preview.html) | 通过本人 MCP Token 跑出的真实账单，门店仅保留城市 |
| [Demo 报告（虚构数据）](https://atemlos5471.github.io/mcd-order-ledger/demo-report.html) | `--demo` 一键生成的完整效果，46 笔虚构订单 |

主人生成的一条真实结论：

> 这一年麦当劳请你吃了 **4 顿**：原价 ¥173.50，实付 ¥0.00，省下 **100%**。
> 最常点「麦香鸡三件套」×3，全是晚餐时段堂食，都在深圳同一家店。

## 它会告诉你什么

- **原价 vs 实付**：省了多少、省下百分之几、几笔用了券
- **券明细**：每笔订单抵扣了多少，一笔一笔列出来
- 月度原价趋势、时段偏好、周几最容易"麦"一下
- 常去门店（脱敏模式可只显示城市）、常点餐品 TOP
- 结合官方营养数据估算总热量，换算成需要慢跑多少公里
- 麦享会积分账户：可用 / 累计 / 已用 / 即将过期（来自 `query-my-account`）

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

### 3. 拉取数据并补全订单详情

```bash
python src/fetch_ledger.py --list-tools          # 先看看有哪些工具、各需要什么入参
python src/fetch_ledger.py --preset orders       # 订单列表 + 商城订单 + 营养表 + 积分账户
python src/enrich_orders.py                      # 逐单 query-order 拿原价/优惠券/就餐方式
```

`order-list` 不返回实付金额且不回商品原价，所以必须走 `enrich_orders.py`
才会得到"原价/实付/优惠"三笔账。原始返回落在 `data/raw/`（已 gitignore，不入库）。

### 4. 生成报告

```bash
python src/build_report.py              # 完整版，本地自用
python src/build_report.py --redact     # 脱敏版，门店只保留城市，适合对外分享
```

产物：`out/mcd-order-ledger.xlsx`（总览 / 月度 / 时段 / 星期 / 门店 / 单品 / 就餐方式 /
优惠券 / 积分 / 订单明细共 10 个 sheet）、`out/annual-report.html`。

## 数据来源

全部来自麦当劳中国官方 MCP 服务（`https://mcp.mcd.cn`，Streamable HTTP），未使用任何网页抓取或非官方接口：

| 工具 | 用途 |
|---|---|
| `order-list` | 历史订单列表（无入参，返回全量） |
| `query-order` | 逐单详情：商品原价 `productPrice`、优惠券明细 `couponList`、就餐方式 `takeWay` |
| `mall-order-list` | 麦麦商城积分兑换 / 购买订单 |
| `list-nutrition-foods` | 官方餐品营养数据，用于热量估算 |
| `query-my-account` | 麦享会积分账户（可用 / 累计 / 冻结 / 即将过期） |

金额口径注意：`order-list` 与 `query-order` 的 `totalAmount` / `realTotalAmount`
在优惠券全额抵扣时都是 `"0"`，**不能直接当作实付**。本项目以 `productPrice`
（商品原价合计）为金额主口径，并在报告页脚明确标注。

详细说明见 [MCP_INTEGRATION.md](./MCP_INTEGRATION.md)。

## 目录结构

```
src/
  mcd_mcp.py         MCP Streamable HTTP / JSON-RPC 客户端（会话、工具列举、调用）
  fetch_ledger.py    拉取订单与营养数据，落盘 data/raw/
  enrich_orders.py   逐单调 query-order 补全原价/优惠券/就餐方式
  ledger.py          结构自适应解析 + 统计分析（不假设固定字段名）
  build_report.py    Excel 台账 + HTML 报告生成，支持 --demo / --redact
docs/
  report-preview.html  真实数据脱敏预览（GitHub Pages 在线可看）
  demo-report.html     虚构数据完整效果
examples/
  sample_orders.json   虚构脱敏示例数据，供 --demo 使用
```

## 为什么是"结构自适应"解析

麦当劳 MCP 各工具的返回字段命名并不统一，且会随版本演进。这里没有硬编码字段名，
而是递归扫描 JSON，找出最像订单的那批记录，再按关键词**分优先级**匹配字段——
例如门店要优先命中 `storeName` 而不是 `storeCode`，金额要优先命中
`productPrice` 而不是 `totalAmount`。

好处是 MCP 升级后大概率仍然能跑；代价是极端结构下可能解析不出，此时用
`--list-tools` 确认返回结构即可。

## 目标用户

- 想知道自己在麦当劳真实消费画像的人
- 想用官方 MCP 做数据分析、而不是再做一遍省钱计算的开发者
- 需要一份 MCP + Streamable HTTP + 数据可视化完整参考实现的同学

## 隐私

- Token 只从环境变量读取，从不写入任何产出文件
- `data/raw/` 与 `out/`（含真实订单）默认 gitignore，不会上传
- `--redact` 输出门店只保留城市与门店类型，隐去地名与门店编码
- 仓库中的 `mcp-config.example.json` 只含 `${MCD_MCP_TOKEN}` 占位符

## 参赛信息

麦当劳程序员创意开发大赛（1024 程序员节）参赛作品，用 WorkBuddy 开发。
本项目为参赛者独立开发，非麦当劳官方产品；餐品信息、价格与供应状态以麦当劳官方渠道实时结果为准。
