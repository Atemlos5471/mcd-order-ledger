"""订单规范化与分析。

麦当劳 MCP 各工具返回结构不完全一致，这里做结构自适应：
不假设固定字段名，而是递归找出"看起来像订单"的记录，再按关键词猜测字段。
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Iterable

TIME_HINT = ("time", "date", "created", "createtime", "paytime", "下单", "时间", "日期")
AMOUNT_HINT = ("payamount", "amount", "total", "price", "pay", "fee", "金额", "实付", "总价")
STORE_HINT = ("storename", "store", "shop", "restaurant", "门店", "餐厅", "餐厅名")
CHANNEL_HINT = ("channel", "type", "mode", "scene", "渠道", "就餐", "方式")
NO_HINT = ("orderno", "orderid", "ordercode", "id", "订单号", "订单编号")
ITEM_HINT = ("items", "products", "goods", "details", "meallist", "orderitems", "skus", "明细", "餐品")
NAME_HINT = ("name", "title", "mealname", "productname", "goodsname", "名称", "餐品名")
QTY_HINT = ("qty", "quantity", "count", "num", "数量")
KCAL_HINT = ("kcal", "energy", "calorie", "热量", "能量", "千卡")

TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y年%m月%d日",
    "%Y%m%d%H%M%S",
    "%Y%m%d",
)


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    match = re.search(r"-?\d+(?:\.\d+)?", str(value).replace(",", ""))
    return float(match.group()) if match else None


def to_dt(value: Any) -> datetime | None:
    if value is None or isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        ts = float(value)
        if ts > 1e12:
            ts /= 1000
        try:
            return datetime.fromtimestamp(ts)
        except (OSError, OverflowError, ValueError):
            return None
    text = str(value).strip()
    if not text:
        return None
    for fmt in TIME_FORMATS:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            continue
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _match_key(key: str, hints: Iterable[str]) -> bool:
    low = str(key).lower()
    return any(h in low for h in hints)


def _pick(node: dict, hints: Iterable[str]) -> Any:
    for key, value in node.items():
        if _match_key(key, hints) and value not in (None, "", [], {}):
            return value
    return None


def _walk(node: Any):
    """深度遍历，产出所有 dict。"""
    if isinstance(node, dict):
        yield node
        for value in node.values():
            yield from _walk(value)
    elif isinstance(node, list):
        for item in node:
            yield from _walk(item)


def _looks_like_order(node: dict) -> int:
    score = 0
    for key in node:
        low = str(key).lower()
        if any(h in low for h in TIME_HINT):
            score += 1
        if any(h in low for h in AMOUNT_HINT):
            score += 2
        if any(h in low for h in NO_HINT):
            score += 1
    return score


def find_order_records(payload: Any) -> list[dict]:
    """从任意嵌套结构里挑出最像订单的那批记录。"""
    candidates: list[list[dict]] = []
    for node in _walk(payload):
        for key, value in node.items():
            if not isinstance(value, list) or not value:
                continue
            if not all(isinstance(item, dict) for item in value):
                continue
            if not _match_key(key, ("order", "list", "record", "data", "result", "订单", "记录")):
                continue
            scored = sum(_looks_like_order(item) for item in value)
            if scored >= len(value):  # 平均每个记录至少命中 1 个特征
                candidates.append(value)
    if not candidates:
        for node in _walk(payload):
            score = _looks_like_order(node)
            if score >= 3:
                candidates.append([node])
    if not candidates:
        return []
    return max(candidates, key=len)


def _extract_items(node: dict) -> list[dict]:
    raw_items = None
    for key, value in node.items():
        if _match_key(key, ITEM_HINT) and isinstance(value, list):
            raw_items = value
            break
    if not raw_items:
        return []
    items = []
    for raw in raw_items:
        if not isinstance(raw, dict):
            continue
        name = _pick(raw, NAME_HINT)
        if not name:
            continue
        items.append(
            {
                "name": str(name).strip(),
                "qty": int(to_float(_pick(raw, QTY_HINT)) or 1),
                "price": to_float(_pick(raw, AMOUNT_HINT)),
            }
        )
    return items


@dataclass
class Order:
    order_no: str = ""
    ts: datetime | None = None
    amount: float = 0.0
    store: str = ""
    channel: str = ""
    items: list[dict] = field(default_factory=list)

    @property
    def month(self) -> str:
        return self.ts.strftime("%Y-%m") if self.ts else "未知"

    @property
    def hour(self) -> int | None:
        return self.ts.hour if self.ts else None


def normalize_orders(payload: Any) -> list[Order]:
    orders: list[Order] = []
    for raw in find_order_records(payload):
        ts = to_dt(_pick(raw, TIME_HINT))
        amount = to_float(_pick(raw, AMOUNT_HINT))
        if ts is None and amount is None:
            continue
        orders.append(
            Order(
                order_no=str(_pick(raw, NO_HINT) or ""),
                ts=ts,
                amount=amount or 0.0,
                store=str(_pick(raw, STORE_HINT) or ""),
                channel=str(_pick(raw, CHANNEL_HINT) or ""),
                items=_extract_items(raw),
            )
        )
    orders.sort(key=lambda o: (o.ts is None, o.ts or datetime.min))
    return orders


def load_nutrition(payload: Any) -> dict[str, float]:
    """从 list-nutrition-foods 返回中抽取 {餐品名小写: 千卡}。"""
    table: dict[str, float] = {}
    for node in _walk(payload):
        name = _pick(node, NAME_HINT)
        kcal = None
        for key, value in node.items():
            if _match_key(key, KCAL_HINT):
                kcal = to_float(value)
                if kcal is not None:
                    break
        if name and kcal:
            table[str(name).strip().lower()] = kcal
    return table


def match_kcal(item_name: str, table: dict[str, float]) -> float | None:
    low = item_name.lower()
    if low in table:
        return table[low]
    for name, kcal in table.items():
        if name and (name in low or low in name):
            return kcal
    return None


PERIODS = [
    ("早餐", 5, 10),
    ("午餐", 10, 14),
    ("下午茶", 14, 17),
    ("晚餐", 17, 21),
    ("夜宵", 21, 29),  # 21:00 之后
]


def period_of(hour: int | None) -> str:
    if hour is None:
        return "未知"
    if hour < 5:
        return "夜宵"
    for name, start, end in PERIODS:
        if start <= hour < end:
            return name
    return "夜宵"


@dataclass
class Summary:
    orders: list[Order]
    count: int = 0
    total: float = 0.0
    avg: float = 0.0
    median: float = 0.0
    max_order: float = 0.0
    first: datetime | None = None
    last: datetime | None = None
    span_days: int = 0
    by_month: list[tuple[str, int, float]] = field(default_factory=list)
    by_period: list[tuple[str, int, float]] = field(default_factory=list)
    by_weekday: list[tuple[str, int]] = field(default_factory=list)
    by_store: list[tuple[str, int, float]] = field(default_factory=list)
    by_item: list[tuple[str, int, float]] = field(default_factory=list)
    total_kcal: float = 0.0
    kcal_matched: int = 0


WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]


def summarize(orders: list[Order], nutrition: dict[str, float] | None = None) -> Summary:
    nutrition = nutrition or {}
    summary = Summary(orders=orders)
    if not orders:
        return summary

    amounts = sorted(o.amount for o in orders)
    dated = [o for o in orders if o.ts]
    summary.count = len(orders)
    summary.total = round(sum(o.amount for o in orders), 2)
    summary.avg = round(summary.total / summary.count, 2)
    summary.median = round(amounts[len(amounts) // 2], 2)
    summary.max_order = round(max(amounts), 2)
    if dated:
        summary.first = min(o.ts for o in dated)
        summary.last = max(o.ts for o in dated)
        summary.span_days = max((summary.last - summary.first).days + 1, 1)

    month_map: dict[str, list[Order]] = defaultdict(list)
    for order in dated:
        month_map[order.month].append(order)
    summary.by_month = [
        (month, len(items), round(sum(o.amount for o in items), 2))
        for month, items in sorted(month_map.items())
    ]

    period_map: dict[str, list[Order]] = defaultdict(list)
    for order in dated:
        period_map[period_of(order.ts.hour)].append(order)
    summary.by_period = [
        (period, len(items), round(sum(o.amount for o in items), 2))
        for period, items in sorted(period_map.items(), key=lambda kv: -len(kv[1]))
    ]

    weekday_counter = Counter(o.ts.weekday() for o in dated)
    summary.by_weekday = [
        (WEEKDAY_CN[day], weekday_counter[day]) for day in range(7) if weekday_counter[day]
    ]

    store_map: dict[str, list[Order]] = defaultdict(list)
    for order in orders:
        if order.store:
            store_map[order.store].append(order)
    summary.by_store = [
        (store, len(items), round(sum(o.amount for o in items), 2))
        for store, items in sorted(store_map.items(), key=lambda kv: -len(kv[1]))[:10]
    ]

    item_counter: Counter[str] = Counter()
    item_amount: dict[str, float] = defaultdict(float)
    kcal_total = 0.0
    matched = 0
    for order in orders:
        for item in order.items:
            item_counter[item["name"]] += item["qty"]
            if item["price"]:
                item_amount[item["name"]] += item["price"] * item["qty"]
            kcal = match_kcal(item["name"], nutrition)
            if kcal:
                kcal_total += kcal * item["qty"]
                matched += item["qty"]
    summary.by_item = [
        (name, qty, round(item_amount.get(name, 0.0), 2))
        for name, qty in item_counter.most_common(15)
    ]
    summary.total_kcal = round(kcal_total, 1)
    summary.kcal_matched = matched
    return summary
