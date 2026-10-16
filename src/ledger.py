"""订单规范化与分析。

麦当劳 MCP 各工具返回结构不完全一致，这里做结构自适应：
不假设固定字段名，而是递归找出"看起来像订单"的记录，再按关键词与优先级匹配字段。

字段口径（以麦当劳 order-list + query-order 为准）：
  productPrice        商品原价合计（元）
  totalAmount         原价合计（部分接口与 productPrice 一致）
  realTotalAmount     实付金额；被优惠券全额抵扣时为 "0"
  totalDiscountAmount 优惠金额
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
CHANNEL_HINT = ("channel", "scene", "渠道", "就餐", "方式", "takeway")
NO_HINT = ("orderno", "orderid", "ordercode", "id", "订单号", "订单编号")
ITEM_HINT = (
    "orderproductlist",
    "productlist",
    "items",
    "products",
    "goods",
    "details",
    "meallist",
    "orderitems",
    "skus",
    "明细",
    "餐品",
)
NAME_HINT = ("productname", "name", "title", "mealname", "goodsname", "名称", "餐品名")
QTY_HINT = ("quantity", "qty", "count", "num", "数量")
KCAL_HINT = ("kcal", "energy", "calorie", "热量", "能量", "千卡")
TAKEWAY_HINT = ("takeway", "take", "取餐", "就餐", "方式", "模式")

GROSS_KEYS = ("productprice", "totalamount", "payamount", "realtotalamount", "amount", "price")
REAL_KEYS = ("realpayamount", "realtotalamount", "payamount", "amount", "totalamount")
DISCOUNT_KEYS = ("totaldiscountamount", "discountamount", "discount", "优惠")

TIME_FORMATS = (
    "%Y-%m-%d %H:%M:%S",
    "%Y/%m/%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%Y年%m月%d日",
    "%Y%m%d%H%M%S",
    "%Y%m%d",
)
WEEKDAY_CN = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
PERIODS = [
    ("早餐", 5, 10),
    ("午餐", 10, 14),
    ("下午茶", 14, 17),
    ("晚餐", 17, 21),
    ("夜宵", 21, 29),
]


def to_float(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
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
    """按 hint 优先级取值：先找 productname/storename 这类精确度高的键，再退回模糊匹配。"""
    for hint in hints:
        for key, value in node.items():
            if hint in str(key).lower() and value not in (None, "", [], {}):
                return value
    return None


def _pick_exact(node: dict, keys: Iterable[str]) -> Any:
    for target in keys:
        for key, value in node.items():
            if str(key).lower() == target and value not in (None, "", [], {}):
                return value
    return None


def _walk(node: Any):
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
            if scored >= len(value):
                candidates.append(value)
    if not candidates:
        for node in _walk(payload):
            if _looks_like_order(node) >= 3:
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


def _extract_coupons(node: dict) -> list[dict]:
    raw = None
    for key, value in node.items():
        if str(key).lower() in ("couponlist", "coupons") and isinstance(value, list):
            raw = value
            break
    if not raw:
        return []
    coupons = []
    for item in raw:
        if not isinstance(item, dict):
            continue
        coupons.append(
            {
                "name": str(_pick(item, NAME_HINT) or ""),
                "amount": to_float(_pick(item, AMOUNT_HINT)) or 0.0,
            }
        )
    return coupons


@dataclass
class Order:
    order_no: str = ""
    ts: datetime | None = None
    amount: float = 0.0          # 实际支付口径（realTotalAmount，抵券为 0 时为 0）
    gross: float = 0.0           # 商品原价合计
    store: str = ""
    channel: str = ""
    items: list[dict] = field(default_factory=list)
    coupons: list[dict] = field(default_factory=list)
    take_way: str = ""

    @property
    def month(self) -> str:
        return self.ts.strftime("%Y-%m") if self.ts else "未知"

    @property
    def hour(self) -> int | None:
        return self.ts.hour if self.ts else None

    @property
    def discount(self) -> float:
        return round(max(self.gross - self.amount, 0.0), 2)


def normalize_orders(payload: Any) -> list[Order]:
    orders: list[Order] = []
    for raw in find_order_records(payload):
        ts = to_dt(_pick(raw, TIME_HINT))
        gross = to_float(_pick_exact(raw, GROSS_KEYS))
        amount = to_float(_pick_exact(raw, REAL_KEYS))
        if gross is None and amount is None:
            gross = to_float(_pick(raw, AMOUNT_HINT))
        if ts is None and gross is None and amount is None:
            continue
        if gross is None:
            gross = amount or 0.0
        if amount is None:
            amount = gross
        orders.append(
            Order(
                order_no=str(_pick(raw, NO_HINT) or ""),
                ts=ts,
                amount=round(float(amount or 0.0), 2),
                gross=round(float(gross or 0.0), 2),
                store=str(_pick(raw, STORE_HINT) or ""),
                channel=str(_pick(raw, CHANNEL_HINT) or _pick(raw, TAKEWAY_HINT) or ""),
                items=_extract_items(raw),
                coupons=_extract_coupons(raw),
                take_way=str(_pick(raw, TAKEWAY_HINT) or ""),
            )
        )
    orders.sort(key=lambda o: (o.ts is None, o.ts or datetime.min))
    return orders


def load_nutrition(payload: Any) -> dict[str, float]:
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
        if name and (name in low or (len(name) >= 2 and low in name)):
            return kcal
    return None


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
    total: float = 0.0            # 实付合计
    gross_total: float = 0.0      # 原价合计
    saved: float = 0.0            # 节省合计
    saved_ratio: float = 0.0
    avg: float = 0.0
    avg_gross: float = 0.0
    median: float = 0.0
    max_order: float = 0.0
    first: datetime | None = None
    last: datetime | None = None
    span_days: int = 0
    coupon_used: int = 0
    by_month: list[tuple[str, int, float]] = field(default_factory=list)
    by_period: list[tuple[str, int, float]] = field(default_factory=list)
    by_weekday: list[tuple[str, int]] = field(default_factory=list)
    by_store: list[tuple[str, int, float]] = field(default_factory=list)
    by_item: list[tuple[str, int, float]] = field(default_factory=list)
    by_channel: list[tuple[str, int]] = field(default_factory=list)
    total_kcal: float = 0.0
    kcal_matched: int = 0
    points: dict = field(default_factory=dict)


def summarize(orders: list[Order], nutrition: dict[str, float] | None = None,
              account: dict | None = None) -> Summary:
    nutrition = nutrition or {}
    summary = Summary(orders=orders)
    if not orders:
        return summary

    amounts = sorted(o.amount for o in orders)
    grosses = sorted(o.gross for o in orders)
    dated = [o for o in orders if o.ts]
    summary.count = len(orders)
    summary.total = round(sum(o.amount for o in orders), 2)
    summary.gross_total = round(sum(o.gross for o in orders), 2)
    summary.saved = round(summary.gross_total - summary.total, 2)
    summary.saved_ratio = round(summary.saved / summary.gross_total * 100, 1) if summary.gross_total else 0.0
    summary.avg = round(summary.total / summary.count, 2)
    summary.avg_gross = round(summary.gross_total / summary.count, 2)
    summary.median = round(amounts[len(amounts) // 2], 2)
    summary.max_order = round(max(grosses), 2)
    summary.coupon_used = sum(1 for o in orders if o.coupons)
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
    summary.by_weekday = [(WEEKDAY_CN[day], weekday_counter[day]) for day in range(7) if weekday_counter[day]]

    channel_counter = Counter(o.take_way or o.channel for o in orders if (o.take_way or o.channel))
    summary.by_channel = [(name, cnt) for name, cnt in channel_counter.most_common()]

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
    if account:
        summary.points = {
            "available": to_float(account.get("availablePoint")) or 0.0,
            "accumulated": to_float(account.get("accumulativePoint")) or 0.0,
            "expired": to_float(account.get("expiredPoint")) or 0.0,
            "expiring": to_float(account.get("currentMouthExpirePoint")) or 0.0,
            "used": to_float(account.get("usedPoint")) or 0.0,
            "currency": str(account.get("currency") or "积分"),
        }
    return summary
