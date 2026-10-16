# WorkBuddy 对话上下文

本项目全程使用腾讯 WorkBuddy 智能体开发。以下为开发过程的关键对话上下文记录。

## 1. 需求起点

用户给出腾讯云开发者社区文章
《WorkBuddy和麦当劳，欢迎你来程序员创意开发大赛》
（https://cloud.tencent.com/developer/article/2758235），要求"读一下然后看看怎么完成"。

WorkBuddy 的动作：
- 抓取文章正文，确认这是「麦当劳程序员创意开发大赛（1024 程序员节）」活动推广。
- 进一步定位到官方规则仓库 `github.com/M-China/mcd-developer-innovation-challenge`，
  拉取 `activityGuidelines.md`、`README.md`、`RANKING.md`、`CONTEST_DECLARATION.md` 原文。
- 定位 MCP 源仓库 `github.com/M-China/mcd-mcp-server`，拉取完整工具列表（30+ Tools）。
- 用 GitHub API 查询实时榜单与头部项目，评估竞争强度。

关键结论：赛事排名 100% 由 GitHub 公开 Star 数决定，与代码评审无关；
报名截止 2026-10-25 23:59，榜单以 2026-10-26 00:00 数据定格；
已报名 717 个项目，当时第 100 名门槛为 11 Star。

## 2. 选题决策

WorkBuddy 给出的判断：榜单头部被"省钱 / 优惠券 / 预算 / 核价"类作品高度占据
（第 1 名 `mcd-saver-strategist` 460★、第 2 名 `mcd-coupon-strategist` 367★、
第 3 名 `McOracle` 309★），正面进入该赛道性价比低。

结合用户既有的 Python / Excel 数据处理强项，提出差异化方案：
把麦当劳 MCP 当作**数据出口**而非下单入口，用官方历史订单做个人年度回顾。

用户确认选择：「麦麦年度账单」方向，并确认尚未申请 MCP Token、将自行申请。

## 3. 开发过程

在 WorkBuddy 中依次完成：

1. 环境准备：创建隔离 Python 虚拟环境，安装 `requests`、`openpyxl`，确认可用。
2. 骨架搭建：新建项目目录，从官方仓库原样拷贝 `CONTEST_DECLARATION.md`（规则要求内容不可改动）。
3. 协议层 `src/mcd_mcp.py`：实现 MCP Streamable HTTP / JSON-RPC 2.0 客户端，
   处理 `initialize` → `notifications/initialized` → `tools/list` → `tools/call`，
   同时兼容 `application/json` 与 `text/event-stream` 两种响应形态，
   回传 `Mcp-Session-Id`，并对 401 / 429 给出可操作提示。
4. 取数层 `src/fetch_ledger.py`：支持 `--list-tools` 实时列出服务端工具与入参 schema，
   支持 `--preset orders` 批量拉取账单所需工具，原始返回落盘 `data/raw/`。
5. 解析层 `src/ledger.py`：因 MCP 各工具返回字段命名不统一且会随版本演进，
   采用结构自适应解析——递归扫描 JSON 找出最像订单的记录，再按关键词匹配
   时间 / 金额 / 门店 / 餐品字段；另含营养表抽取与热量模糊匹配。
6. 产出层 `src/build_report.py`：生成 Excel 六表台账（总览 / 月度 / 时段 / 星期 / 门店 / 单品 / 明细）
   与单文件 HTML 年度报告（内联 SVG 图表，无外部依赖，可直接分享）。
7. 示例数据 `examples/sample_orders.json`：虚构脱敏数据，使项目可在无 Token 情况下
   通过 `--demo` 一键跑通全流程。

## 4. 验证记录

```
$ python src/build_report.py --demo
订单 46 笔，合计 ¥2,604.00
已生成: out/mcd-order-ledger.xlsx
已生成: out/annual-report.html
```

报告自检输出（示例数据）：

- 这一年你在麦当劳花了 ¥2,604.00，按巨无霸单价 ¥25 估算，约等于 104.2 个巨无霸。
- 最常点的是「麦辣鸡翅(2块)」，共 18 份，稳居你的麦麦 C 位。
- 你最偏好的时段是午餐，贡献了 19 笔订单。
- 最常光顾的门店是「上海南京西路店」，14 笔、累计 ¥694.00。
- 已匹配到的餐品热量合计约 54,810 kcal，相当于慢跑 843.2 公里才能消耗完。

合规自检：
- 全库扫描未发现硬编码 Token / 密钥；
- `mcp-config.example.json` 仅含 `${MCD_MCP_TOKEN}` 占位符；
- `.env` 与 `data/raw/`（真实订单）均已 gitignore。

## 5. 待用户完成的步骤

- 在 https://open.mcd.cn/mcp 用本人手机号登录并申请 MCP Token；
- 写入项目根目录 `.env` 的 `MCD_MCP_TOKEN`；
- 运行 `python src/fetch_ledger.py --preset orders` 拉取真实订单；
- 运行 `python src/build_report.py` 生成真实年度报告，并回填 README 效果图；
- 于 2026-10-25 23:59 前在官方仓库用指定 Issue 模板提交报名。
