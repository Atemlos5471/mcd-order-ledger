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

## 6. Token 到位后的真实数据开发（2026-10-16 18:00 后）

用户提供 MCP Token，进入真实数据联调。WorkBuddy 的动作与关键发现：

1. `--list-tools` 实测连通：服务端返回 **35 个工具**（早于官方 README 的 30+），
   工具描述已是新版分节格式（When / Input / Next / Preconditions）。
2. `--preset orders` 拉取四个工具成功。但暴露出 md 版 README 未写的问题：
   - `order-list` **无入参**，返回全量；`mall-order-list` 返回 `hasNext=false, list=[]`（空）。
   - 订单仅 4 笔（2026-04-21 至 2026-10-13），门店集中在深圳两家。
   - **`realTotalAmount` / `totalAmount` 全为 `"0"`**，列表接口不回商品原价。

3. 定位到解决方案：`query-order`（需 orderId）逐单查详情，实测返回
   `productPrice: "39.5"`、`couponList: [{couponName: "麦香鸡三件套", discountAmount: "39.5"}]`、
   `takeWay: "堂食"`、`storeAddress`。即实付为 0 是用券全额抵扣，原价 39.5。

   由此确定金额口径：原价取 `productPrice`，实付取 `realTotalAmount`，节省 = 原价 − 实付，
   报告首页结论从"花了多少钱"改为"**麦当劳请了你多少顿**"。

4. 新增 `src/enrich_orders.py`：对每笔订单调 `query-order`，合并详情字段，落盘
   `data/raw/order-list-enriched.json`，支持 `--redact` 不保存门店详细地址。

5. 重构 `src/ledger.py`：字段匹配改为**按 hint 优先级**（修掉门店误取 `storeCode`
   显示为 "1420825" 的 bug）；新增优惠券、就餐方式、积分账户维度。

6. 重构 `src/build_report.py`：新增原价/实付对比 hero 区、优惠券明细表、就餐方式分布、
   积分账户表；Excel 扩到 10 个 sheet；新增 `--redact` 脱敏模式（门店只保留城市与类型，
   隐去地名与门店编码）。

7. 产物：
   - 本地完整版：`out/annual-report.html` + `out/mcd-order-ledger.xlsx`（含真实门店名，不外传）
   - 仓库展示版：`docs/report-preview.html`（真实数据、门店脱敏）与 `docs/demo-report.html`
     （虚构数据完整效果），用于 GitHub Pages 在线预览。
   - 脱敏校验通过：预览版不含门店地址、不含订单号、门店仅显示"麦当劳深圳·某门店"等。

8. 真实数据结论（已写入 README）：4 笔订单，原价 ¥173.50，实付 ¥0.00，节省 100%；
   麦香鸡三件套 ×3，全为晚餐堂食；麦享会可用积分 357.7。

9. 合规复核：`.env`、`data/raw/`、`out/` 均已在 `.gitignore`；
   仓库内所有文件扫描无 Token、无门店地址、无订单号。
