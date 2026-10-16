"""生成麦麦年度账单：Excel 多sheet 台账 + 单文件 HTML 年度报告。

用法：
    python src/build_report.py --demo                 # 用示例数据跑通全流程
    python src/build_report.py                        # 读取 data/raw/ 下的真实拉取结果
    python src/build_report.py --orders data/raw/order-list.json --out out/
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
INK = "#292726"


# ---------------- 数据装载 ----------------
def load_json(path: Path):
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def collect_inputs(args) -> tuple[list[Order], dict[str, float], dict | None]:
    orders: list[Order] = []
    nutrition: dict[str, float] = {}
    account: dict | None = None

    if args.demo:
        sample = load_json(ROOT / "examples" / "sample_orders.json")
        orders = normalize_orders(sample)
        nutrition = load_nutrition(sample.get("nutrition", []))
        return orders, nutrition, None

    for name in ("order-list", "mall-order-list"):
        payload = load_json(Path(args.orders) if args.orders and name == "order-list" else RAW_DIR / f"{name}.json")
        if payload:
            orders.extend(normalize_orders(payload))

    nutrition_payload = load_json(Path(args.nutrition) if args.nutrition else RAW_DIR / "list-nutrition-foods.json")
    if nutrition_payload:
        nutrition = load_nutrition(nutrition_payload)

    account_payload = load_json(Path(args.account) if args.account else RAW_DIR / "query-my-account.json")
    if account_payload:
        account = account_payload
    return orders, nutrition, account


# ---------------- Excel ----------------
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
            ["总花费(元)", summary.total],
            ["客单价(元)", summary.avg],
            ["订单金额中位数(元)", summary.median],
            ["单笔最高(元)", summary.max_order],
            ["首单日期", summary.first.strftime("%Y-%m-%d") if summary.first else "-"],
            ["末单日期", summary.last.strftime("%Y-%m-%d") if summary.last else "-"],
            ["覆盖天数", summary.span_days],
            ["估算总热量(kcal)", summary.total_kcal],
        ],
    )
    sheet("月度", ["月份", "订单数", "花费(元)"], [list(r) for r in summary.by_month])
    sheet("时段", ["时段", "订单数", "花费(元)"], [list(r) for r in summary.by_period])
    sheet("星期", ["星期", "订单数"], [list(r) for r in summary.by_weekday])
    sheet("门店", ["门店", "订单数", "花费(元)"], [list(r) for r in summary.by_store])
    sheet("单品", ["餐品", "份数", "金额(元)"], [list(r) for r in summary.by_item])
    sheet(
        "订单明细",
        ["订单号", "时间", "金额(元)", "门店", "渠道"],
        [
            [o.order_no, o.ts.strftime("%Y-%m-%d %H:%M") if o.ts else "-", o.amount, o.store, o.channel]
            for o in summary.orders
        ],
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    wb.save(path)


# ---------------- HTML ----------------
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
        f'aria-label="月度订单数柱状图">{"".join(bars)}</svg>'
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
            f'{value:.0f}{unit}</text>'
        )
    return f'<svg viewBox="0 0 {width} {height}" width="100%" role="img">{"".join(rows)}</svg>'


def metric_cards(summary) -> str:
    cards = [
        ("订单总数", f"{summary.count}", "笔"),
        ("总花费", f"¥{summary.total:,.2f}", ""),
        ("客单价", f"¥{summary.avg:,.2f}", ""),
        ("单笔最高", f"¥{summary.max_order:,.2f}", ""),
    ]
    items = "".join(
        f'<div class="card"><div class="card-label">{label}</div>'
        f'<div class="card-value">{value}</div>'
        f'<div class="card-unit">{unit}</div></div>'
        for label, value, unit in cards
    )
    return f'<div class="cards">{items}</div>'


def build_findings(summary) -> list[str]:
    findings = []
    if not summary.count:
        return ["暂无订单数据，先运行 fetch_ledger.py 拉取真实订单。"]
    big_mac = 25.0
    findings.append(
        f"这一年你在麦当劳花了 ¥{summary.total:,.2f}，按巨无霸单价 ¥{big_mac:.0f} 估算，"
        f"约等于 {summary.total / big_mac:.1f} 个巨无霸。"
    )
    if summary.by_item:
        name, qty, _ = summary.by_item[0]
        findings.append(f"最常点的是「{name}」，共 {qty} 份，稳居你的麦麦 C 位。")
    if summary.by_period:
        period, count, _ = summary.by_period[0]
        findings.append(f"你最偏好的时段是{period}，贡献了 {count} 笔订单。")
    if summary.by_store:
        store, count, amount = summary.by_store[0]
        findings.append(f"最常光顾的门店是「{store}」，{count} 笔、累计 ¥{amount:,.2f}。")
    if summary.by_weekday:
        day, count = max(summary.by_weekday, key=lambda kv: kv[1])
        findings.append(f"{day}是你的麦麦高频日，共 {count} 笔。")
    if summary.total_kcal:
        findings.append(
            f"已匹配到的餐品热量合计约 {summary.total_kcal:,.0f} kcal，"
            f"相当于慢跑 {summary.total_kcal / 65:.1f} 公里才能消耗完。"
        )
    if summary.span_days and summary.count > 1:
        findings.append(
            f"从 {summary.first:%Y-%m-%d} 到 {summary.last:%Y-%m-%d}，"
            f"{summary.span_days} 天里平均 {summary.span_days / summary.count:.1f} 天吃一次。"
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
  header p {{ margin: 0; font-size: 14px; opacity: .9; }}
  .cards {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(150px, 1fr)); gap: 12px; margin: 20px 0; }}
  .card {{ background: #fff; border: 1px solid #EFE6D2; border-radius: 12px; padding: 16px; }}
  .card-label {{ font-size: 13px; color: #6B6A67; }}
  .card-value {{ font-size: 24px; font-weight: 600; margin-top: 6px; color: var(--red); }}
  .card-unit {{ font-size: 12px; color: #9A988F; }}
  section {{ background: #fff; border: 1px solid #EFE6D2; border-radius: 12px; padding: 20px; margin-top: 16px; }}
  section h2 {{ margin: 0 0 16px; font-size: 17px; font-weight: 600; }}
  section h2 span {{ font-size: 13px; font-weight: 400; color: #9A988F; margin-left: 8px; }}
  ul {{ margin: 0; padding-left: 20px; line-height: 1.9; font-size: 14px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 14px; }}
  th, td {{ text-align: left; padding: 8px 6px; border-bottom: 1px solid #F2ECDC; }}
  th {{ color: #6B6A67; font-weight: 500; }}
  td.num {{ text-align: right; font-variant-numeric: tabular-nums; }}
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
<section>
  <h2>这一年，你和麦当劳</h2>
  <ul>{findings}</ul>
</section>
{month_section}
{period_section}
{item_section}
{store_section}
<footer>
  数据来源：麦当劳中国官方 MCP 服务（order-list / mall-order-list / list-nutrition-foods）。<br>
  本项目为麦当劳程序员创意开发大赛参赛作品，由参赛者独立开发，非麦当劳官方产品；
  餐品信息、价格与订单数据以麦当劳官方渠道实时结果为准。
</footer>
</div>
</body>
</html>
"""


def make_section(title: str, note: str, body: str) -> str:
    return f'<section><h2>{title}<span>{note}</span></h2>{body}</section>'


def write_html(summary, path: Path) -> None:
    subtitle = "基于麦当劳 MCP 真实订单数据生成"
    if summary.first and summary.last:
        subtitle = f"{summary.first:%Y-%m-%d} 至 {summary.last:%Y-%m-%d} · 共 {summary.count} 笔订单"
    month_section = (
        make_section("月度订单分布", "按下单月份统计", svg_columns([(m, float(c)) for m, c, _ in summary.by_month]))
        if summary.by_month
        else ""
    )
    period_section = (
        make_section("时段偏好", "你通常在几点吃麦当劳", svg_bars([(p, float(c)) for p, c, _ in summary.by_period], " 笔"))
        if summary.by_period
        else ""
    )
    item_section = (
        make_section("常点餐品 TOP", "按累计份数", svg_bars([(n, float(q)) for n, q, _ in summary.by_item[:10]], " 份"))
        if summary.by_item
        else ""
    )
    store_rows = "".join(
        f"<tr><td>{html.escape(s)}</td><td class='num'>{c}</td><td class='num'>¥{a:,.2f}</td></tr>"
        for s, c, a in summary.by_store[:8]
    )
    store_section = (
        make_section(
            "常去门店",
            "按订单数",
            f"<table><tr><th>门店</th><th style='text-align:right'>订单数</th>"
            f"<th style='text-align:right'>花费</th></tr>{store_rows}</table>",
        )
        if store_rows
        else ""
    )
    content = HTML_TEMPLATE.format(
        title="我的麦麦年度账单",
        subtitle=subtitle,
        gold=GOLD,
        red=RED,
        ink=INK,
        cards=metric_cards(summary),
        findings="".join(f"<li>{html.escape(f)}</li>" for f in build_findings(summary)),
        month_section=month_section,
        period_section=period_section,
        item_section=item_section,
        store_section=store_section,
    )
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


# ---------------- CLI ----------------
def main() -> int:
    parser = argparse.ArgumentParser(description="生成麦麦年度账单报告")
    parser.add_argument("--demo", action="store_true", help="使用示例数据，无需 Token")
    parser.add_argument("--orders", help="order-list 原始 JSON")
    parser.add_argument("--nutrition", help="list-nutrition-foods 原始 JSON")
    parser.add_argument("--account", help="query-my-account 原始 JSON")
    parser.add_argument("--out", default=str(OUT_DIR), help="输出目录")
    args = parser.parse_args()

    orders, nutrition, _ = collect_inputs(args)
    summary = summarize(orders, nutrition)
    if not summary.count:
        print("未解析到订单。若已拉取真实数据，请用 --list-tools 确认工具返回结构。", file=sys.stderr)

    out_dir = Path(args.out)
    write_excel(summary, out_dir / "mcd-order-ledger.xlsx")
    write_html(summary, out_dir / "annual-report.html")
    print(f"订单 {summary.count} 笔，合计 ¥{summary.total:,.2f}")
    print(f"已生成: {out_dir / 'mcd-order-ledger.xlsx'}")
    print(f"已生成: {out_dir / 'annual-report.html'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
