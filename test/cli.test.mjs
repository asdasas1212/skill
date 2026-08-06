import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const root = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");
const cli = path.join(root, "bin", "paper-preread.mjs");

test("CLI reports version", () => {
  const result = spawnSync(process.execPath, [cli, "version"], { encoding: "utf8" });
  assert.equal(result.status, 0);
  assert.equal(result.stdout.trim(), "0.1.0");
});

test("CLI help documents safe Phase 6", () => {
  const result = spawnSync(process.execPath, [cli, "help"], { encoding: "utf8" });
  assert.equal(result.status, 0);
  assert.match(result.stdout, /without --commit/);
});

test("Phase 6 creates a plan without remote writes", () => {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "paper-preread-phase6-"));
  fs.mkdirSync(path.join(fixture, "_modules"));
  fs.mkdirSync(path.join(fixture, "figures"));
  fs.writeFileSync(path.join(fixture, "figures", "figure.png"), "not-a-real-png");
  const modules = ["背景", "问题", "结论", "技术", "实验", "讨论"];
  for (const moduleName of modules) {
    const content = moduleName === "技术"
      ? `## ${moduleName}\n\n说明\n\n![架构图](figures/figure.png)`
      : `## ${moduleName}\n\n内容`;
    fs.writeFileSync(
      path.join(fixture, "_modules", `${moduleName}.json`),
      JSON.stringify({ module_id: moduleName, content_md: content }),
    );
  }
  const result = spawnSync(process.execPath, [cli, "phase6", "--out-dir", fixture], { encoding: "utf8" });
  assert.equal(result.status, 0, result.stderr);
  const plan = JSON.parse(fs.readFileSync(path.join(fixture, "phase6_export.json"), "utf8"));
  assert.equal(plan.status, "needs_parent");
  assert.equal(plan.operations.filter((item) => item.type === "insert_media").length, 1);
  assert.equal(fs.existsSync(path.join(fixture, "phase6_state.json")), false);
});

test("Phase 6 auto-selects the only profile that can read the parent", () => {
  const fixture = fs.mkdtempSync(path.join(os.tmpdir(), "paper-preread-routing-"));
  fs.mkdirSync(path.join(fixture, "_modules"));
  for (const moduleName of ["背景", "问题", "结论", "技术", "实验", "讨论"]) {
    fs.writeFileSync(
      path.join(fixture, "_modules", `${moduleName}.json`),
      JSON.stringify({ module_id: moduleName, content_md: `## ${moduleName}\n\n内容` }),
    );
  }
  const fakeBin = path.join(fixture, "bin");
  fs.mkdirSync(fakeBin);
  const fakeLark = path.join(fakeBin, "lark-cli");
  fs.writeFileSync(fakeLark, `#!/bin/sh
if [ "$1 $2" = "profile list" ]; then
  printf '%s\\n' '[{"name":"personal","active":true},{"name":"cowa","active":false}]'
elif printf '%s\\n' "$*" | grep -q -- '--profile cowa'; then
  printf '%s\\n' '{"ok":true,"data":{"node_token":"wikcn-parent","space_id":"123"}}'
else
  printf '%s\\n' '{"ok":false,"error":{"type":"permission"}}' >&2
  exit 1
fi
`, { mode: 0o755 });
  const python = spawnSync("/usr/bin/env", ["python3", "--version"], { encoding: "utf8" });
  assert.equal(python.status, 0);
  const phase6 = path.join(root, "paper-preread", "scripts", "phase6_write.py");
  const result = spawnSync("python3", [phase6, "--out-dir", fixture, "--parent", "https://example.feishu.cn/wiki/fake"], {
    encoding: "utf8",
    env: { ...process.env, PATH: `${fakeBin}:${process.env.PATH}` },
  });
  assert.equal(result.status, 0, result.stderr);
  const plan = JSON.parse(fs.readFileSync(path.join(fixture, "phase6_export.json"), "utf8"));
  assert.equal(plan.profile, "cowa");
  assert.equal(plan.parent_node_token, "wikcn-parent");
  assert.equal(fs.existsSync(path.join(fixture, "phase6_state.json")), false);
});
