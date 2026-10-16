"""用 query-order 补全订单详情。

麦当劳 order-list 返回的列表不含商品原价，且实付金额常为 0（被优惠券全额抵扣）。
query-order 会返回商品原价 productPrice、实付、优惠券明细、就餐方式与门店地址。

用法：
    python src/enrich_orders.py                                   # 默认处理 data/raw/order-list.json
    python src/enrich_orders.py --input a.json --out b.json
    python src/enrich_orders.py --redact                          # 门店地址不落盘（脱敏）
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcd_mcp import McpError, get_client  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        import os

        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))

DETAIL_FIELDS = (
    "productPrice",
    "totalAmount",
    "realTotalAmount",
    "totalDiscountAmount",
    "deliveryPrice",
    "realDeliveryPrice",
    "takeWay",
    "storeAddress",
    "couponList",
    "payId",
    "remark",
)


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def extract_orders(payload) -> list[dict]:
    """兼容 data.list / list / data 三种返回形态。"""
    if isinstance(payload, list):
        return payload
    data = payload.get("data", payload) if isinstance(payload, dict) else payload
    if isinstance(data, dict):
        for key in ("list", "orderList", "orders", "records"):
            if isinstance(data.get(key), list):
                return data[key]
        return [data]
    if isinstance(data, list):
        return data
    return []


def main() -> int:
    parser = argparse.ArgumentParser(description="补全订单详情")
    parser.add_argument("--input", default=str(RAW_DIR / "order-list.json"))
    parser.add_argument("--out", default=str(RAW_DIR / "order-list-enriched.json"))
    parser.add_argument("--redact", action="store_true", help="不保存门店详细地址")
    args = parser.parse_args()

    source = Path(args.input)
    if not source.exists():
        print(f"未找到 {source}，请先运行 fetch_ledger.py", file=sys.stderr)
        return 1

    orders = extract_orders(load(source))
    if not orders:
        print("没有订单需要补全", file=sys.stderr)
        return 1

    _load_dotenv()
    client = get_client()
    enriched = []
    for index, order in enumerate(orders, 1):
        order_id = order.get("orderId") or order.get("orderNo")
        if not order_id:
            enriched.append(order)
            continue
        try:
            detail = client.call_tool("query-order", {"orderId": str(order_id)})
        except McpError as exc:
            print(f"[{index}/{len(orders)}] {order_id} 失败: {exc}", file=sys.stderr)
            enriched.append(order)
            continue
        merged = dict(order)
        payload = detail.get("data") or {}
        if isinstance(payload, dict):
            target = payload.get("data", payload) if payload.get("code") else payload
        else:
            target = {}
        for field in DETAIL_FIELDS:
            if field in target:
                merged[field] = target[field]
        # 商品级单位价补到明细上
        detail_items = (target or {}).get("orderProductList") or []
        for item, src in zip(merged.get("orderProductList", []), detail_items):
            if "price" in src:
                item["price"] = src["price"]
        if args.redact:
            merged.pop("storeAddress", None)
        enriched.append(merged)
        product_price = merged.get("productPrice")
        real = merged.get("realTotalAmount")
        print(f"[{index}/{len(orders)}] {order_id} 原价={product_price} 实付={real}")

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(
        json.dumps({"data": {"list": enriched}}, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(f"\n已写出: {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
