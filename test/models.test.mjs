import assert from "node:assert/strict";
import { mkdtempSync, mkdirSync, writeFileSync } from "node:fs";
import os from "node:os";
import path from "node:path";
import { spawnSync } from "node:child_process";
import test from "node:test";

const projectRoot = path.resolve(import.meta.dirname, "..");
const sourceRoot = path.join(projectRoot, "pdf-extract", "src");

function runModelDownload(key) {
  const tempRoot = mkdtempSync(path.join(os.tmpdir(), "paper-preread-models-"));
  const fakeModules = path.join(tempRoot, "fake-modules");
  const cacheRoot = path.join(tempRoot, "cache");
  mkdirSync(fakeModules);
  writeFileSync(
    path.join(fakeModules, "huggingface_hub.py"),
    `from pathlib import Path
def snapshot_download(repo_id, local_dir, allow_patterns):
    assert repo_id == 'opendatalab/PDF-Extract-Kit-1.0'
    assert local_dir == r'${cacheRoot}'
    assert allow_patterns[1].endswith('/*')
    target = Path(local_dir) / allow_patterns[0]
    if target.suffix:
        target.parent.mkdir(parents=True, exist_ok=True)
        target.touch()
    else:
        target.mkdir(parents=True, exist_ok=True)
        (target / 'model.bin').touch()
`,
  );

  const result = spawnSync(
    "python3.10",
    [
      "-c",
      `import importlib.util
spec = importlib.util.spec_from_file_location('models', r'${path.join(sourceRoot, "paper_extract", "models.py")}')
models = importlib.util.module_from_spec(spec)
spec.loader.exec_module(models)
print(models._download('${key}'))`,
    ],
    {
      encoding: "utf8",
      env: {
        ...process.env,
        PAPER_EXTRACT_CACHE: cacheRoot,
        PYTHONPATH: `${fakeModules}${path.delimiter}${sourceRoot}`,
      },
    },
  );
  assert.equal(result.status, 0, result.stderr);
  return { cacheRoot, output: result.stdout.trim() };
}

test("model files download without a duplicated models directory", () => {
  const { cacheRoot, output } = runModelDownload("layout");
  assert.equal(output, path.join(cacheRoot, "models/Layout/YOLO/doclayout_yolo_ft.pt"));
});

test("model directories include their contents", () => {
  const { cacheRoot, output } = runModelDownload("formula_rec");
  assert.equal(output, path.join(cacheRoot, "models/MFR/unimernet_tiny"));
});
