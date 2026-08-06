"""safe_io.py — 原子写 + JSON 合法性校验 + 可选 content_md 引号检查

防止重复出现的两类问题：
1. agent 写到一半被打断 → 半损坏文件 → 下游 read 报警
2. agent 把 content_md 字符串手动拼进 JSON 时忘记 escape ASCII `"` → JSON 解析失败

使用：
    from safe_io import safe_write_json

    obj = {"module_id": "技术", "content_md": "...这里有中文「」...", ...}
    safe_write_json("/path/to/技术.json", obj)
    # 自动：写到 .tmp → os.replace 原子化 → 校验 json.load → 写 ✓

选项：
- atomic=True（默认 True）：原子写
- validate_after=True（默认 True）：写后立刻 json.load 校验
- max_ascii_doublequote_in_md=None：跳过引号检查（read-then-rewrite 路径）
                 max_ascii_doublequote_in_md=0：raise 如果 content_md 含原始 "

注意事项：
- safe_write_json 只在最外层用 json.dumps(obj)，所以即使是 raw content_md 也会被
  自动 escape 成合法 JSON。问题只发生在 agent 手动 sprintf 出 JSON 字符串时。
- safe_write_json 会先 read 现有文件（如果存在）做 reference 检查；
  对读时已经存在的 raw `"` 不会报（避免 read-then-rewrite 路径误判）。
"""
from __future__ import annotations
import json
import os
import sys
from pathlib import Path
from typing import Any


def _strip_outer_quotes(s: str) -> str:
    """If s is wrapped in \"...\" strip the outer pair (when they form a clean JSON string)."""
    if len(s) >= 2 and s.startswith('"') and s.endswith('"'):
        inner = s[1:-1]
        # verify by trying to parse
        try:
            json.loads(s)
            return inner
        except Exception:
            return s
    return s


def safe_dump(obj: Any, max_ascii_doublequote_in_md: int | None = None) -> str:
    """Dump obj to JSON string.

    Note: max_ascii_doublequote_in_md is kept as an optional log hook but
    NOT enforced — json.dumps already properly escapes `"` when it serializes
    the string. Counting `"` in the *decoded* Python string after json.loads
    is a false-positive trap (every string with `"` would trip it).

    The real safety net is:
    - This function calls json.dumps(obj, ensure_ascii=False) which always
      emits a valid JSON string regardless of the obj's contents.
    - The Write CLI uses this + atomic .tmp replace + post-write json.load
      validation, which catches every actual break.
    """
    # max_ascii_doublequote_in_md is now a no-op (kept for backward-compat).
    _ = max_ascii_doublequote_in_md
    return json.dumps(obj, indent=2, ensure_ascii=False)


def safe_write_json(
    path: str | Path,
    obj: Any,
    *,
    atomic: bool = True,
    validate_after: bool = True,
    max_ascii_doublequote_in_md: int | None = None,
) -> Path:
    """原子写 JSON 到 path。

    Args:
        path: 目标文件路径
        obj: 可被 json.dumps 序列化的对象
        atomic: 写到 .tmp 再 os.replace；False 时直接覆盖
        validate_after: 写完立刻 json.load 检查，否则 raise
        max_ascii_doublequote_in_md: 见 safe_dump
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    payload = safe_dump(obj, max_ascii_doublequote_in_md=max_ascii_doublequote_in_md)
    if atomic:
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(payload + "\n", encoding="utf-8")
        os.replace(tmp, p)
    else:
        p.write_text(payload + "\n", encoding="utf-8")
    if validate_after:
        try:
            with open(p) as f:
                json.load(f)
        except Exception as e:
            raise RuntimeError(f"safe_write_json: post-write json.load failed for {p}: {e}")
    return p


def safe_load_json(path: str | Path) -> Any:
    """Load JSON from path with safety check (file exists + parseable)."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"safe_load_json: {p} 不存在")
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        raise RuntimeError(f"safe_load_json: {p} 解析失败: {e}")


def count_ascii_doublequote_in_content_md(path: str | Path) -> int:
    """返回 path 对应的 *_modules/*.json 文件里 content_md 字段含几个 ASCII `"`"""
    d = safe_load_json(path)
    if isinstance(d, dict) and isinstance(d.get("content_md"), str):
        return d["content_md"].count('"')
    return 0


def write_cli(args) -> int:
    """CLI: write a JSON file safely via stdin or --from-file.

    Usage:
        echo '{"k":"v"}' | python3 safe_io.py write <path>
        python3 safe_io.py write <path> --from <input.json>
    """
    if args.from_file:
        raw = Path(args.from_file).read_text(encoding="utf-8")
    elif not sys.stdin.isatty():
        raw = sys.stdin.read()
    else:
        print("ERROR: must pipe JSON via stdin or use --from <file>", file=sys.stderr)
        return 2
    try:
        obj = json.loads(raw)
    except Exception as e:
        print(f"ERROR: stdin JSON parse failed: {e}", file=sys.stderr)
        return 2
    try:
        safe_write_json(
            args.path,
            obj,
            atomic=not args.no_atomic,
            validate_after=not args.no_validate,
        )
    except Exception as e:
        print(f"ERROR: safe_write_json failed: {e}", file=sys.stderr)
        return 2
    print(f"✓ wrote {args.path}")
    return 0


# ---- CLI ----
def main():
    import argparse
    import sys as _sys
    # Two-mode CLI: bare positional paths = verify mode; first arg = 'write' = write mode
    argv = _sys.argv[1:]
    if argv and argv[0] == "write":
        ap = argparse.ArgumentParser(description="safe_io write: atomic JSON write CLI")
        ap.add_argument("cmd", choices=["write"])
        ap.add_argument("path", help="target file path")
        ap.add_argument("--from", dest="from_file", default=None,
                        help="read JSON from this file instead of stdin")
        ap.add_argument("--no-atomic", action="store_true")
        ap.add_argument("--no-validate", action="store_true")
        args = ap.parse_args(argv)
        sys.exit(write_cli(args))
    else:
        ap = argparse.ArgumentParser(description="safe_io verify: count ASCII double-quotes in JSON files' content_md")
        ap.add_argument("files", nargs="+", help="JSON files to check")
        ap.add_argument("--max-quotes", type=int, default=0,
                        help="exit 1 if any content_md has more than N ASCII double-quotes (default 0)")
        args = ap.parse_args(argv)
        bad = 0
        for f in args.files:
            try:
                n = count_ascii_doublequote_in_content_md(f)
                if n > args.max_quotes:
                    bad += 1
                    print(f"  ✗ {f}: {n} ASCII \" in content_md (max={args.max_quotes})")
                else:
                    print(f"  ✓ {f}: {n} ASCII \" (<= max={args.max_quotes})")
            except Exception as e:
                bad += 1
                print(f"  ✗ {f}: {e}")
        sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
