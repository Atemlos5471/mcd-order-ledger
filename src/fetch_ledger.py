"""从麦当劳 MCP 拉取账单原始数据。

用法：
    python src/fetch_ledger.py --list-tools
    python src/fetch_ledger.py --tool order-list --arg pageSize=50
    python src/fetch_ledger.py --preset orders        # 拉取账单所需的一批工具
    python src/fetch_ledger.py --tool query-my-account --out data/raw/account.json
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from mcd_mcp import McpError, get_client  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
RAW_DIR = ROOT / "data" / "raw"

# 账单场景默认拉取的工具清单
PRESET = ["order-list", "mall-order-list", "query-my-account", "list-nutrition-foods"]


def _load_dotenv() -> None:
    env_file = ROOT / ".env"
    if not env_file.exists():
        return
    for line in env_file.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def parse_args_kv(pairs: list[str]) -> dict:
    out: dict = {}
    for pair in pairs:
        if "=" not in pair:
            raise SystemExit(f"参数格式错误: {pair}（应为 key=value）")
        key, _, raw = pair.partition("=")
        try:
            out[key.strip()] = json.loads(raw)
        except (ValueError, TypeError):
            out[key.strip()] = raw
    return out


def cmd_list_tools(client) -> None:
    tools = client.list_tools()
    print(f"共 {len(tools)} 个工具：\n")
    for tool in tools:
        schema = tool.get("inputSchema", {})
        required = schema.get("required", []) or []
        props = schema.get("properties", {}) or {}
        args = ", ".join(f"{k}{'*' if k in required else ''}" for k in props) or "无入参"
        print(f"- {tool.get('name')}")
        print(f"    {tool.get('description', '').strip()}")
        print(f"    入参: {args}\n")


def save(name: str, payload) -> Path:
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    path = RAW_DIR / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


def main() -> int:
    parser = argparse.ArgumentParser(description="拉取麦当劳 MCP 账单原始数据")
    parser.add_argument("--list-tools", action="store_true", help="列出所有可用 MCP 工具")
    parser.add_argument("--tool", help="要调用的工具名")
    parser.add_argument("--arg", action="append", default=[], help="工具入参，格式 key=value，可重复")
    parser.add_argument("--out", help="输出文件路径（默认 data/raw/<tool>.json）")
    parser.add_argument("--preset", choices=["orders"], help="按预设批量拉取")
    parser.add_argument("--raw", action="store_true", help="同时打印返回原文")
    args = parser.parse_args()

    _load_dotenv()
    client = get_client()

    if args.list_tools:
        cmd_list_tools(client)
        return 0

    targets: list[tuple[str, dict]] = []
    if args.tool:
        targets.append((args.tool, parse_args_kv(args.arg)))
    elif args.preset == "orders":
        targets.extend((name, {}) for name in PRESET)
    else:
        parser.error("需要 --list-tools / --tool / --preset 之一")

    for name, arguments in targets:
        try:
            result = client.call_tool(name, arguments)
        except McpError as exc:
            print(f"[失败] {name}: {exc}", file=sys.stderr)
            continue
        if result["is_error"]:
            print(f"[工具报错] {name}: {result['text'][:300]}", file=sys.stderr)
            continue
        out_path = Path(args.out) if (args.out and len(targets) == 1) else save(name, result["data"] or result["text"])
        if args.out and len(targets) == 1:
            out_path.parent.mkdir(parents=True, exist_ok=True)
            out_path.write_text(
                json.dumps(result["data"] or result["text"], ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
        print(f"[完成] {name} -> {out_path}")
        if args.raw:
            print(result["text"][:2000])

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
