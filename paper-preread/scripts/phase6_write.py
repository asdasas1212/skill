#!/usr/bin/env python3
"""Build or execute the Phase 6 Lark/Feishu write plan.

The script is deliberately safe by default. Without --commit it writes
phase6_export.json and exits without changing remote state. If lark-cli is not
installed, the same export remains usable by an Agent after lark-cli is added.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any


IMAGE_RE = re.compile(r"!\[([^\]]*)\]\(([^)]+)\)")


class Phase6Error(RuntimeError):
    pass


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise Phase6Error(f"required file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise Phase6Error(f"invalid JSON in {path}: {exc}") from exc


def run_json(argv: list[str], cwd: Path) -> dict[str, Any]:
    proc = subprocess.run(argv, cwd=cwd, text=True, capture_output=True)
    stream = proc.stdout.strip() or proc.stderr.strip()
    try:
        payload = json.loads(stream)
    except json.JSONDecodeError as exc:
        raise Phase6Error(
            f"command returned non-JSON output ({proc.returncode}): {' '.join(argv)}\n{stream}"
        ) from exc
    if proc.returncode != 0 or payload.get("ok") is False:
        raise Phase6Error(
            f"command failed ({proc.returncode}): {' '.join(argv)}\n"
            f"{json.dumps(payload, ensure_ascii=False)}"
        )
    return payload


def module_order(skill_dir: Path, out_dir: Path) -> list[dict[str, Any]]:
    manifest_path = out_dir / "manifest.json"
    if not manifest_path.exists():
        manifest_path = skill_dir / "manifest.json"
    manifest = load_json(manifest_path)
    modules = manifest.get("modules")
    if not isinstance(modules, list) or not modules:
        raise Phase6Error(f"manifest has no modules: {manifest_path}")
    return sorted(modules, key=lambda item: item.get("index", 999))


def resolve_media(out_dir: Path, raw_path: str, inverse: dict[str, str]) -> Path:
    cleaned = raw_path.strip().split("#", 1)[0].split("?", 1)[0]
    direct = (out_dir / cleaned).resolve()
    out_root = out_dir.resolve()
    if direct == out_root or out_root not in direct.parents:
        raise Phase6Error(f"unsafe media path outside output directory: {raw_path}")
    if direct.is_file():
        return direct
    short_name = Path(cleaned).name
    original = inverse.get(short_name)
    if original:
        resolved = (out_dir / original).resolve()
        if resolved.is_file() and out_root in resolved.parents:
            return resolved
    raise Phase6Error(f"media file not found: {raw_path}")


def build_operations(skill_dir: Path, out_dir: Path) -> list[dict[str, Any]]:
    aliases_path = out_dir / "figures_alias.json"
    aliases = load_json(aliases_path) if aliases_path.exists() else {"_inverse": {}}
    inverse = aliases.get("_inverse", {})
    operations: list[dict[str, Any]] = []
    for module in module_order(skill_dir, out_dir):
        module_path = out_dir / "_modules" / module["filename"]
        module_doc = load_json(module_path)
        content = module_doc.get("content_md")
        if not isinstance(content, str):
            raise Phase6Error(f"content_md missing in {module_path}")
        cursor = 0
        for match in IMAGE_RE.finditer(content):
            text = content[cursor : match.start()].strip()
            if text:
                operations.append({"type": "append_markdown", "content": text})
            media = resolve_media(out_dir, match.group(2), inverse)
            operations.append(
                {
                    "type": "insert_media",
                    "file": str(media.relative_to(out_dir)),
                    "caption": match.group(1).strip(),
                }
            )
            cursor = match.end()
        tail = content[cursor:].strip()
        if tail:
            operations.append({"type": "append_markdown", "content": tail})
    return operations


def infer_title(out_dir: Path) -> str:
    for filename in ("paper_context.json", "meta.json", "paper_meta.json"):
        path = out_dir / filename
        if not path.exists():
            continue
        doc = load_json(path)
        for key in ("title", "paper_title"):
            value = doc.get(key) if isinstance(doc, dict) else None
            if isinstance(value, str) and value.strip():
                return value.strip()
    return out_dir.name or "论文精读"


def raw_profile_list(cwd: Path) -> list[dict[str, Any]]:
    proc = subprocess.run(["lark-cli", "profile", "list"], cwd=cwd, text=True, capture_output=True)
    if proc.returncode != 0:
        raise Phase6Error(proc.stderr.strip() or "failed to list lark-cli profiles")
    data = json.loads(proc.stdout)
    return data if isinstance(data, list) else data.get("data", [])


def select_profile(parent: str, requested: str, cwd: Path) -> tuple[str, dict[str, Any]]:
    profiles = raw_profile_list(cwd)
    names = [item.get("name") for item in profiles if item.get("name")]
    if requested != "auto":
        if requested not in names:
            raise Phase6Error(f"lark-cli profile not found: {requested}")
        node = run_json(
            ["lark-cli", "--profile", requested, "wiki", "+node-get", "--node-token", parent, "--as", "user", "--format", "json"],
            cwd,
        )
        return requested, node

    matches: list[tuple[str, dict[str, Any]]] = []
    for name in names:
        proc = subprocess.run(
            ["lark-cli", "--profile", name, "wiki", "+node-get", "--node-token", parent, "--as", "user", "--format", "json"],
            cwd=cwd,
            text=True,
            capture_output=True,
        )
        if proc.returncode == 0:
            try:
                payload = json.loads(proc.stdout)
            except json.JSONDecodeError:
                continue
            if payload.get("ok", True):
                matches.append((name, payload))
    if not matches:
        raise Phase6Error("no configured lark-cli profile can access the parent Wiki node")
    if len(matches) == 1:
        return matches[0]
    active = next((item.get("name") for item in profiles if item.get("active")), None)
    if active:
        for match in matches:
            if match[0] == active:
                return match
    raise Phase6Error(
        "multiple profiles can access the parent; pass --profile explicitly: "
        + ", ".join(name for name, _ in matches)
    )


def data_of(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data", payload)
    return data if isinstance(data, dict) else {}


def plan_hash(plan: dict[str, Any]) -> str:
    stable = {
        "title": plan["title"],
        "profile": plan["profile"],
        "parent_node_token": plan["parent_node_token"],
        "operations": plan["operations"],
    }
    encoded = json.dumps(stable, sort_keys=True, ensure_ascii=False).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def execute(plan: dict[str, Any], out_dir: Path, export_dir: Path) -> dict[str, Any]:
    profile = plan["profile"]
    parent_token = plan["parent_node_token"]
    state_path = out_dir / "phase6_state.json"
    state = load_json(state_path) if state_path.exists() else {}
    current_hash = plan_hash(plan)
    previous_hash = state.get("plan_hash")
    if previous_hash and previous_hash != current_hash:
        raise Phase6Error(
            f"Phase 6 inputs changed since the last write; move or remove {state_path} "
            "before starting a new document"
        )
    document_id = state.get("document_id")
    if not document_id:
        created = run_json(
            [
                "lark-cli", "--profile", profile, "wiki", "+node-create",
                "--parent-node-token", parent_token, "--title", plan["title"],
                "--obj-type", "docx", "--as", "user", "--format", "json",
            ],
            out_dir,
        )
        created_data = data_of(created)
        document_id = created_data.get("obj_token") or created_data.get("document_id")
        if not document_id:
            raise Phase6Error(f"node creation returned no document token: {created_data}")
        state = {
            "schema_version": 1,
            "plan_hash": current_hash,
            "profile": profile,
            "document_id": document_id,
            "node_token": created_data.get("node_token"),
            "completed_operations": 0,
        }
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    start = int(state.get("completed_operations", 0))
    for index, operation in enumerate(plan["operations"][start:], start=start):
        if operation["type"] == "append_markdown":
            chunk = export_dir / f"chunk-{index + 1:04d}.md"
            chunk.write_text(operation["content"] + "\n", encoding="utf-8")
            relative = chunk.relative_to(out_dir)
            run_json(
                [
                    "lark-cli", "--profile", profile, "docs", "+update",
                    "--doc", document_id, "--command", "append", "--doc-format", "markdown",
                    "--content", f"@{relative}", "--as", "user", "--format", "json",
                ],
                out_dir,
            )
        elif operation["type"] == "insert_media":
            argv = [
                "lark-cli", "--profile", profile, "docs", "+media-insert",
                "--doc", document_id, "--file", operation["file"], "--align", "center",
                "--width", "720", "--as", "user", "--format", "json",
            ]
            if operation.get("caption"):
                argv.extend(["--caption", operation["caption"]])
            run_json(argv, out_dir)
        else:
            raise Phase6Error(f"unsupported operation: {operation}")
        state["completed_operations"] = index + 1
        state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    state["status"] = "complete"
    state_path.write_text(json.dumps(state, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return state


def main() -> int:
    parser = argparse.ArgumentParser(description="Plan or execute paper-preread Phase 6")
    parser.add_argument("--out-dir", default=".")
    parser.add_argument("--parent", help="parent Wiki URL or node token")
    parser.add_argument("--profile", default="auto", help="lark-cli profile name or auto")
    parser.add_argument("--title")
    parser.add_argument("--commit", action="store_true", help="perform remote writes")
    args = parser.parse_args()

    out_dir = Path(args.out_dir).expanduser().resolve()
    skill_dir = Path(__file__).resolve().parent.parent
    operations = build_operations(skill_dir, out_dir)
    export_dir = out_dir / "_phase6_export"
    export_dir.mkdir(exist_ok=True)
    plan: dict[str, Any] = {
        "schema_version": 1,
        "status": "planned",
        "title": args.title or infer_title(out_dir),
        "parent": args.parent,
        "profile": args.profile,
        "operations": operations,
    }

    lark_available = shutil.which("lark-cli") is not None
    if args.parent and lark_available:
        profile, node_payload = select_profile(args.parent, args.profile, out_dir)
        node_data = data_of(node_payload)
        plan["profile"] = profile
        plan["parent_node_token"] = node_data.get("node_token") or node_data.get("token")
        plan["parent_space_id"] = node_data.get("space_id")
        if not plan["parent_node_token"]:
            raise Phase6Error(f"could not resolve parent node token: {node_data}")
    elif args.parent:
        plan["status"] = "needs_lark_cli"
        plan["next_command"] = "npx @larksuite/cli@latest install"
    else:
        plan["status"] = "needs_parent"

    export_path = out_dir / "phase6_export.json"
    export_path.write_text(json.dumps(plan, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"✓ Phase 6 plan: {export_path}")

    if not args.commit:
        print("No remote changes made. Re-run with --commit to write to Feishu/Lark.")
        return 0
    if not args.parent:
        raise Phase6Error("--parent is required with --commit")
    if not lark_available:
        print("lark-cli is not installed; export preserved for a later retry", file=sys.stderr)
        return 2
    state = execute(plan, out_dir, export_dir)
    print(json.dumps(state, indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except Phase6Error as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(1)
