"""生成麦麦年度账单：Excel 多sheet 台账 + 单文件 HTML 年度报告。

用法：
    python src/build_report.py --demo        # 用示例数据跑通全流程，无需 Token
    python src/build_report.py               # 读取 data/raw/ 下的真实拉取结果
    python src/build_report.py --redact      # 脱敏模式：不输出门店详细地址
"""

from __future__ import annotations

import argparse
import html
import json
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from ledger import Order, load_nutrition, normalize_orders, summarize  # noqa: E402
from openpyxl import Workbook  # noqa: E402
from openpyxl.styles import Alignment, Font, PatternFill  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"
OUT_DIR = ROOT / "out"

GOLD = "#FFC72C"
RED = "#DA291C"
GREEN = "#3B7D3B"
INK = "#292726"


def load_json(path: Path | None):
    if not path or not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _exists(path: Path) -> bool:
    return path.exists() and path.read_text(encoding="utf-8").strip() not in ("", "{}", "[]")


def collect_inputs(args) -> tuple[list[Order], dict[str, float], dict | None]:
    orders: list[Order] = []
    nutrition: dict[str, float] = {}
    account: dict | None = None

    if args.demo:
        sample = load_json(ROOT / "examples" / "sample_orders.json")
        orders = normalize_orders(sample)
        nutrition = load_nutrition(sample.get("nutrition", []))
        return orders, nutrition, None

    enriched = load_json(Path(args.orders) if args.orders else RAW_DIR / "order-list-enriched.json")
    plain = load_json(Path(args.orders) if args.orders else RAW_DIR / "order-list.json")
    orders = normalize_orders(enriched if enriched else plain)

    nutrition_payload = load_json(Path(args.nutrition) if args.nutrition else RAW_DIR / "list-nutrition-foods.json")
    if nutrition_payload:
        nutrition = load_nutrition(nutrition_payload)

    account_payload = load_json(Path(args.account) if args.account else RAW_DIR / "query-my-account.json")
    if account_payload:
        data = account_payload.get("data", account_payload) if isinstance(account_payload, dict) else {}
        account = data if isinstance(data, dict) and data else None
    return orders, nutrition, account


def write_excel(summary, path: Path) -> None:
    wb = Workbook()
    head_font = Font(bold=True, color="FFFFFF")
    head_fill = PatternFill("solid", fgColor="DA291C")

    def sheet(title: str, header: list[str], rows: list[list]):
        ws = wb.create_sheet(title)
        ws.append(header)
        for cell in ws[1]:
            cell.font = head_font
            cell.fill = head_fill
            cell.alignment = Alignment(horizontal="center")
        for row in rows:
            ws.append(row)
        for column in ws.columns:
            width = max(len(str(cell.value or "")) for cell in column) + 4
            ws.column_dimensions[column[0].column_letter].width = min(width, 40)
        return ws

    wb.remove(wb.active)
    sheet(
        "总览",
        ["指标", "数值"],
        [
            ["订单总数", summary.count],
            ["原价合计(元)", summary.gross_total],
            ["实付合计(元)", summary.total],
            ["节省合计(元)", summary.saved],
            ["节省比例", f"{summary.saved_ratio}%"],
            ["单均原价(元)", summary.avg_gross],
            ["单均实付(元)", summary.avg],
            ["单笔原价最高(元)", summary.max_order],
            ["用券订单数", summary.coupon_used],
            ["首单日期", summary.first.strftime("%Y-%m-%d") if summary.first else "-"],
            ["末单日期", summary.last.strftime("%Y-%m-%d") if summary.last else "-"],
            ["覆盖天数", summary.span_days],
            ["估算总热量(kcal)", summary.total_kcal],
        ],
    )
    sheet("月度", ["月份", "订单数", "原价(元)", "实付(元)"], [list(r) for r in summary.by_month])
    sheet("时段", ["时段", "订单数", "实付(元)"], [list(r) for r in summary.by_period])
    sheet("星期", ["星期", "订单数"], [list(r) for r in summary.by_weekday])
    sheet("门店", ["门店", "订单数", "实付(元)"], [list(r) for r in summary.by_store])
    sheet("单品", ["餐品", "份数", "金额(元)"], [list(r) for r in summary.by_item])
    sheet("就餐方式", ["方式", "订单数"], [list(r) for r in summary.by_channel])
    coupon_rows = [
        [o.ts.strftime("%Y-%m-%d") if o.ts else "-", c["name"], f"{c['amount']:.2f}"]
        for o in summary.orders
        for c in o.coupons
    ]
    if coupon_rows:
        sheet("优惠券", ["日期", "优惠券", "抵扣金额(元)"], coupon_rows)
    if summary.points:
        sheet(
            "积分账户",
            ["项目", "数值"],
            [[k, summary.points[k]] for k in ("currency", "available", "accumulated", "used", "expired", "expiring")],
        )
    sheet(
        "订单明细",
        ["订单号", "时间", "原价(元)", "实付(元)", "优惠(元)", "门店", "就餐方式"],
        [
            [
                o.order_no,
                o.ts.strftime("%Y-%m-%d %H:%M") if o.ts else "-",
                o.gross,
                o.amount,
                o.discount,
                o.store,
                o.take_way or o.channel,
            ]
            for o in summary.orders
        ],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


def svg_columns(data: list[tuple[str, float]], width=660, height=200) -> str:
    if not data:
        return ""
    max_value = max(value for _, value in data) or 1
    padding, gap = 28, 8
    bar_width = (width - padding * 2 - gap * (len(data) - 1)) / max(len(data), 1)
    bars = []
    for index, (label, value) in enumerate(data):
        bar_height = (value / max_value) * (height - 60)
        x = padding + index * (bar_width + gap)
        y = height - 34 - bar_height
        bars.append(
            f'<rect x="{x:.1f}" y="{y:.1f}" width="{bar_width:.1f}" height="{bar_height:.1f}" rx="3" fill="{RED}"/>'
            f'<text x="{x + bar_width / 2:.1f}" y="{y - 6:.1f}" text-anchor="middle" '
            f'font-size="11" fill="{INK}">{value:.0f}</text>'
            f'<text x="{x + bar_width / 2:.1f}" y="{height - 16:.1f}" text-anchor="middle" '
            f'font-size="11" fill="#6B6A67">{html.escape(str(label)[5:])}</text>'
        )
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="月度原价柱状图">{"".join(bars)}</svg>'
    )


def svg_bars(data: list[tuple[str, float]], unit: str = "", width=660) -> str:
    if not data:
        return ""
    max_value = max(value for _, value in data) or 1
    row_height, label_width = 34, 150
    height = row_height * len(data) + 10
    rows = []
    for index, (label, value) in enumerate(data):
        y = index * row_height + 6
        bar_length = (value / max_value) * (width - label_width - 90)
        rows.append(
            f'<text x="0" y="{y + 15:.1f}" font-size="13" fill="{INK}">{html.escape(str(label))}</text>'
            f'<rect x="{label_width}" y="{y + 3:.1f}" width="{max(bar_length, 2):.1f}" height="17" rx="4" fill="{GOLD}"/>'
            f'<text x="{label_width + max(bar_length, 2) + 8:.1f}" y="{y + 16:.1f}" font-size="12" fill="#6B6A67">'
            f"{value:,.0f}{unit}</text>"
        )
    return f'<svg viewBox="0 0 {width} {height}" width="100%" role="img">{"".join(rows)}</svg>'


def svg_compare(gross: float, paid: float, width=660) -> str:
    if gross <= 0:
        return ""
    max_value = gross or 1
    height, label_width, bar_h = 96, 90, 22
    paid_len = (paid / max_value) * (width - label_width - 130)
    gross_len = width - label_width - 130
    return (
        f'<svg viewBox="0 0 {width} {height}" width="100%" role="img" '
        f'aria-label="原价与实付对比">'
        f'<text x="0" y="26" font-size="13" fill="{INK}">原价</text>'
        f'<rect x="{label_width}" y="12" width="{gross_len:.1f}" height="{bar_h}" rx="4" fill="#B4B2A9"/>'
        f'<text x="{label_width + gross_len + 8:.1f}" y="28" font-size="13" fill="#6B6A67">¥{gross:,.2f}</text>'
        f'<text x="0" y="66" font-size="13" fill="{INK}">实付</text>'
        f'<rect x="{label_width}" y="52" width="{max(paid_len, 3):.1f}" height="{bar_h}" rx="4" fill="{RED}"/>'
        f'<text x="{label_width + max(paid_len, 3) + 8:.1f}" y="68" font-size="13" fill="{RED}">¥{paid:,.2f}</text>'
        f"</svg>"
    )


def metric_cards(summary) -> str:
    cards = [
        ("实际支付", f"¥{summary.total:,.2f}", RED),
        ("原价合计", f"¥{summary.gross_total:,.2f}", INK),
        ("省下的钱", f"¥{summary.saved:,.2f}", GREEN),
        ("订单数", f"{summary.count}", INK),
    ]
    items = "".join(
        f'<div class="card"><div class="card-label">{label}</div>'
        f'<div class="card-value" style="color:{color}">{value}</div></div>'
        for label, value, color in cards
    )
    return f'<div class="cards">{items}</div>'


def build_findings(summary) -> list[str]:
    if not summary.count:
        return ["暂无订单数据，先运行 fetch_ledger.py 拉取真实订单。"]
    findings = []
    if summary.saved > 0 and summary.gross_total > 0:
        findings.append(
            f"这一年麦当劳请你吃了 {summary.coupon_used} 顿：原价 ¥{summary.gross_total:,.2f}，"
            f"实付 ¥{summary.total:,.2f}，省下 ¥{summary.saved:,.2f}（{summary.saved_ratio}%）。"
        )
    else:
        findings.append(
            f"原价 ¥{summary.gross_total:,.2f}，实付 ¥{summary.total:,.2f}，"
            f"单均 ¥{summary.avg:,.2f}。"
        )
    big_mac = 25.0
    findings.append(
        f"按原价折算，你吃掉了约 {summary.gross_total / big_mac:.1f} 个巨无霸的量。"
    )
    if summary.by_item:
        name, qty, _ = summary.by_item[0]
        findings.append(f"最常点的是「{name}」，共 {qty} 份，稳居你的麦麦 C 位。")
    if summary.by_period:
        period, count, _ = summary.by_period[0]
        findings.append(f"你最偏爱的时段是{period}，贡献了 {count} 笔订单。")
    if summary.by_store:
        store, count, _ = summary.by_store[0]
        findings.append(f"最常光顾「{store}」，共 {count} 笔。")
    if summary.by_weekday:
        day, count = max(summary.by_weekday, key=lambda kv: kv[1])
        findings.append(f"{day}是你的麦麦高频日，共 {count} 笔。")
    if summary.by_channel:
        way, count = summary.by_channel[0]
        findings.append(f"{way}是你最常选择的方式，{count} 笔。")
    if summary.total_kcal:
        findings.append(
            f"已匹配到的餐品热量合计约 {summary.total_kcal:,.0f} kcal，"
            f"相当于慢跑 {summary.total_kcal / 65:.1f} 公里才能消耗完。"
        )
    if summary.span_days and summary.count > 1:
        findings.append(
            f"从 {summary.first:%Y-%m-%d} 到 {summary.last:%Y-%m-%d}，{summary.span_days} 天里"
            f"平均 {summary.span_days / summary.count:.1f} 天去一次麦当劳。"
        )
    return findings


HTML_TEMPLATE = """<!DOCTYPE html>
<html lang="zh-CN">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  :root {{ --gold: {gold}; --red: {red}; --ink: {ink}; }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; padding: 32px 16px 64px; background: #FFFDF7; color: var(--ink);
         font-family: -apple-system, "PingFang SC", "Microsoft YaHei", system-ui, sans-serif; }}
  .wrap {{ max-width: 720px; margin: 0 auto; }}
  header {{ background: var(--red); color: #fff; border-radius: 16px; padding: 28px 24px; }}
  header h1 {{ margin: 0 0 8px; font-size: 26px; font-weight: 600; }}
  header p {{ margin: 0; font-size: 14px; opacity: .92; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 20px 0; }}
  .card {{ background: #fff; border: 1px solid #EFE6D2; border-radius: 12px; padding: 16px; }}
  .card-label {{ font-size: 13px; color: #6B6A67; }}
  .card-value {{ font-size: 23px; font-weight: 600; margin-top: 6px; }}
  section {{ background: #fff; border: 1px solid #EFE6D2; border-radius: 12px; padding: 20px; margin-top: 16px; }}
  section h2 {{ margin: 0 0 16px; font-size: 17px; font-weight: 600; }}
  section h2 span {{ font-size: 13px; font-weight: 400; color: #9A988F; margin-left: 8px; }}
  ul {{ margin: 0; padding-left: 20px; line-height: 1.95; font-size: 14px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ text-align: left; padding: 8px 6px; border-bottom: 1px solid #F2ECDC; }}
  th {{ color: #6B6A67; font-weight: 500; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
  .note {{ font-size: 12px; color: #9A988F; margin-top: 12px; line-height: 1.7; }}
  footer {{ margin-top: 24px; font-size: 12px; color: #9A988F; line-height: 1.8; }}
</style>
</head>
<body>
<div class="wrap">
<header>
  <h1>{title}</h1>
  <p>{subtitle}</p>
</header>
{cards}
{hero_section}
<section>
  <h2>这一年，你和麦当劳</h2>
  <ul>{findings}</ul>
</section>
{month_section}
{period_section}
{item_section}
{store_section}
{coupon_section}
{channel_section}
{points_section}
<footer>
  数据来源：麦当劳中国官方 MCP 服务（order-list / query-order / mall-order-list /
  list-nutrition-foods / query-my-account）。<br>
  金额口径说明：订单列表接口不返回实付金额，故以 query-order 返回的商品原价为准；
  实付金额被优惠券全额抵扣时显示为 0。<br>
  本项目为麦当劳程序员创意开发大赛参赛作品，由参赛者独立开发，非麦当劳官方产品；
  餐品信息、价格与订单数据以麦当劳官方渠道实时结果为准。
</footer>
</div>
</body>
</html>
"""


def make_section(title: str, note: str, body: str) -> str:
    return f"<section><h2>{title}<span>{note}</span></h2>{body}</section>"


def write_html(summary, path: Path, redact: bool = False) -> None:
    subtitle = "基于麦当劳 MCP 真实订单数据生成"
    if summary.first and summary.last:
        subtitle = f"{summary.first:%Y-%m-%d} 至 {summary.last:%Y-%m-%d} · 共 {summary.count} 笔订单"
    month_section = (
        make_section(
            "月度原价分布",
            "按下单月份统计",
            svg_columns([(m, float(a)) for m, c, a in summary.by_month]),
        )
        if summary.by_month
        else ""
    )
    period_section = (
        make_section(
            "时段偏好",
            "你通常在几点吃麦当劳",
            svg_bars([(p, float(c)) for p, c, _ in summary.by_period], " 笔"),
        )
        if summary.by_period
        else ""
    )
    item_section = (
        make_section(
            "常点餐品 TOP",
            "按累计份数",
            svg_bars([(n, float(q)) for n, q, _ in summary.by_item[:10]], " 份"),
        )
        if summary.by_item
        else ""
    )
    store_rows = "".join(
        f"<tr><td>{html.escape(_mask_store(s, redact))}</td><td class='num'>{c}</td>"
        f"<td class='num'>¥{a:,.2f}</td></tr>"
        for s, c, a in summary.by_store[:8]
    )
    store_section = (
        make_section(
            "常去门店",
            "按订单数",
            f"<table><tr><th>门店</th><th style='text-align:right'>订单数</th>"
            f"<th style='text-align:right'>实付</th></tr>{store_rows}</table>",
        )
        if store_rows
        else ""
    )
    coupon_rows = "".join(
        f"<tr><td>{html.escape(_mask_store(s, redact))}</td><td>{html.escape(n)}</td>"
        f"<td class='num'>-¥{a:,.2f}</td></tr>"
        for o in summary.orders
        for n, a in ((c["name"], c["amount"]) for c in o.coupons)
        for s in [o.store]
    )
    coupon_section = (
        make_section(
            "优惠券明细",
            "抵扣了多少，一笔一笔算给你看",
            f"<table><tr><th>门店</th><th>优惠券</th><th style='text-align:right'>抵扣</th></tr>{coupon_rows}</table>",
        )
        if coupon_rows
        else ""
    )
    channel_body = svg_bars([(c, float(n)) for c, n in summary.by_channel], " 笔")
    channel_section = make_section("就餐方式", "堂食 / 外带 / 外送", channel_body) if channel_body else ""
    points_section = ""
    if summary.points:
        p = summary.points
        points_section = make_section(
            f"{p.get('currency', '积分')}账户",
            "来自 query-my-account",
            f"<table><tr><th>项目</th><th style='text-align:right'>数值</th></tr>"
            f"<tr><td>可用积分</td><td class='num'>{p['available']:,.1f}</td></tr>"
            f"<tr><td>累计获得积分</td><td class='num'>{p['accumulated']:,.1f}</td></tr>"
            f"<tr><td>已使用积分</td><td class='num'>{p['used']:,.1f}</td></tr>"
            f"<tr><td>即将过期积分</td><td class='num'>{p['expiring']:,.1f}</td></tr>"
            f"<tr><td>已过期积分</td><td class='num'>{p['expired']:,.1f}</td></tr></table>",
        )
    hero = ""
    if summary.saved > 0 and summary.gross_total > 0:
        hero = make_section(
            "麦当劳请你吃了多少顿",
            f"原价 vs 实付，省下 {summary.saved_ratio}%",
            svg_compare(summary.gross_total, summary.total)
            + f"<div class='note'>共 {summary.coupon_used} 笔订单使用了优惠券，"
            f"累计抵扣 ¥{summary.saved:,.2f}。</div>",
        )
    content = HTML_TEMPLATE.format(
        title="我的麦麦年度账单",
        subtitle=subtitle,
        gold=GOLD,
        red=RED,
        ink=INK,
        cards=metric_cards(summary),
        hero_section=hero,
        findings="".join(f"<li>{html.escape(f)}</li>" for f in build_findings(summary)),
        month_section=month_section,
        period_section=period_section,
        item_section=item_section,
        store_section=store_section,
        coupon_section=coupon_section,
        channel_section=channel_section,
        points_section=points_section,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


CITIES = (
    "北京", "上海", "广州", "深圳", "成都", "杭州", "南京", "武汉", "西安", "重庆",
    "天津", "苏州", "长沙", "郑州", "青岛", "厦门", "福州", "合肥", "昆明", "东莞",
    "佛山", "珠海", "宁波", "无锡", "哈尔滨", "沈阳", "大连", "济南", "贵阳", "南宁",
)


def _mask_store(name: str, redact: bool) -> str:
    """脱敏规则：保留城市与门店类型（得来速等），隐去地标/路名，避免暴露具体活动范围。"""
    if not redact or not name:
        return name
    for city in CITIES:
        if city in name:
            tail = "得来速" if "得来速" in name else ("甜品店" if "甜品" in name else "")
            return f"麦当劳{city}·{tail + '餐厅' if tail else '某门店'}"
    return "麦当劳某门店"


def main() -> int:
    parser = argparse.ArgumentParser(description="生成麦麦年度账单报告")
    parser.add_argument("--demo", action="store_true", help="使用示例数据，无需 Token")
    parser.add_argument("--orders", help="订单原始 JSON（可选）")
    parser.add_argument("--nutrition", help="list-nutrition-foods 原始 JSON")
    parser.add_argument("--account", help="query-my-account 原始 JSON")
    parser.add_argument("--redact", action="store_true", help="脱敏：门店名截断（用于公开分享）")
    parser.add_argument("--out", default=str(OUT_DIR), help="输出目录")
    args = parser.parse_args()

    orders, nutrition, account = collect_inputs(args)
    summary = summarize(orders, nutrition, account)
    if not summary.count:
        print("未解析到订单。若已拉取真实数据，请确认 data/raw/ 下文件内容。", file=sys.stderr)

    out_dir = Path(args.out)
    write_excel(summary, out_dir / "mcd-order-ledger.xlsx")
    write_html(summary, out_dir / "annual-report.html", redact=args.redact)
    print(f"订单 {summary.count} 笔 | 原价 ¥{summary.gross_total:,.2f} | 实付 ¥{summary.total:,.2f} | 省 ¥{summary.saved:,.2f}")
    print(f"已生成: {out_dir / 'mcd-order-ledger.xlsx'}")
    print(f"已生成: {out_dir / 'annual-report.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
