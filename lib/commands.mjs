import { spawnSync } from "node:child_process";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";

export function runtimeHome() {
  return process.env.PAPER_PREREAD_HOME || path.join(os.homedir(), ".paper-preread");
}

function run(command, args, options = {}) {
  const result = spawnSync(command, args, {
    encoding: "utf8",
    stdio: options.capture ? "pipe" : "inherit",
    cwd: options.cwd,
    env: { ...process.env, ...options.env },
  });
  if (result.error) throw result.error;
  if (options.capture) return result;
  if (result.status !== 0) throw new Error(`${command} exited with status ${result.status}`);
  return result;
}

function commandPath(command) {
  const result = spawnSync("/usr/bin/env", ["sh", "-c", `command -v ${command}`], {
    encoding: "utf8",
    stdio: "pipe",
  });
  return result.status === 0 ? result.stdout.trim() : "";
}

function packageCopyFilter(source) {
  const name = path.basename(source);
  if (name === ".git" || name === "__pycache__" || name.endsWith(".egg-info")) return false;
  if (name.endsWith(".pyc") || name.endsWith(".bak")) return false;
  return true;
}

function replaceTree(source, destination) {
  const staging = `${destination}.staging-${process.pid}`;
  fs.rmSync(staging, { recursive: true, force: true });
  fs.mkdirSync(path.dirname(destination), { recursive: true });
  fs.cpSync(source, staging, { recursive: true, dereference: false, filter: packageCopyFilter });
  fs.rmSync(destination, { recursive: true, force: true });
  fs.renameSync(staging, destination);
}

function syncRuntimePackage(packageRoot, destination) {
  const staging = `${destination}.staging-${process.pid}`;
  fs.rmSync(staging, { recursive: true, force: true });
  fs.mkdirSync(staging, { recursive: true });
  for (const entry of ["package.json", "bin", "lib", "paper-preread", "pdf-extract"]) {
    const source = path.join(packageRoot, entry);
    const target = path.join(staging, entry);
    fs.cpSync(source, target, { recursive: true, dereference: false, filter: packageCopyFilter });
  }
  fs.rmSync(destination, { recursive: true, force: true });
  fs.renameSync(staging, destination);
}

function pythonInVenv(home) {
  return process.platform === "win32"
    ? path.join(home, "venv", "Scripts", "python.exe")
    : path.join(home, "venv", "bin", "python");
}

const UV_VERSION = "0.11.32";

async function download(url, destination) {
  const curl = commandPath("curl");
  if (curl) {
    run(curl, ["--fail", "--location", "--retry", "3", "--output", destination, url]);
    fs.chmodSync(destination, 0o700);
    return;
  }
  const response = await fetch(url, { redirect: "follow" });
  if (!response.ok) throw new Error(`download failed (${response.status}): ${url}`);
  const bytes = new Uint8Array(await response.arrayBuffer());
  fs.writeFileSync(destination, bytes, { mode: 0o700 });
}

async function uvInvocation(home) {
  const uv = commandPath("uv");
  if (uv) return [uv, []];
  if (process.platform === "win32") {
    throw new Error("automatic uv bootstrap is not available on Windows yet");
  }
  const toolDir = path.join(home, "tools", "uv");
  const localUv = path.join(toolDir, "uv");
  if (fs.existsSync(localUv)) return [localUv, []];

  fs.mkdirSync(toolDir, { recursive: true });
  const installer = path.join(home, `uv-install-${UV_VERSION}.sh`);
  console.log(`[runtime] downloading standalone uv ${UV_VERSION} (no system Python needed)`);
  await download(`https://astral.sh/uv/${UV_VERSION}/install.sh`, installer);
  try {
    run("/bin/sh", [installer], {
      env: { UV_UNMANAGED_INSTALL: toolDir, UV_NO_MODIFY_PATH: "1" },
    });
  } finally {
    fs.rmSync(installer, { force: true });
  }
  if (!fs.existsSync(localUv)) throw new Error(`uv installer did not create ${localUv}`);
  return [localUv, []];
}

function installLauncher(home) {
  if (process.platform === "win32") return;
  const binDir = process.env.PAPER_PREREAD_BIN_DIR || path.join(os.homedir(), ".local", "bin");
  fs.mkdirSync(binDir, { recursive: true });
  const launcher = path.join(binDir, "paper-preread");
  const target = path.join(home, "package", "bin", "paper-preread.mjs");
  fs.writeFileSync(launcher, `#!/bin/sh\nexec "${process.execPath}" "${target}" "$@"\n`, { mode: 0o755 });
}

function readRuntimeConfig(home) {
  const configPath = path.join(home, "config.json");
  if (!fs.existsSync(configPath)) return {};
  try {
    return JSON.parse(fs.readFileSync(configPath, "utf8"));
  } catch {
    return {};
  }
}

function writeRuntimeConfig(home, values) {
  const merged = { ...readRuntimeConfig(home), ...values };
  fs.writeFileSync(path.join(home, "config.json"), `${JSON.stringify(merged, null, 2)}\n`);
}

export async function install(packageRoot, { installModels = true, skillsOnly = false } = {}) {
  const home = runtimeHome();
  const sharedSkills = process.env.PAPER_PREREAD_SKILLS_DIR || path.join(os.homedir(), ".agents", "skills");
  console.log(`[skills] installing into ${sharedSkills}`);
  for (const name of ["paper-preread", "pdf-extract"]) {
    replaceTree(path.join(packageRoot, name), path.join(sharedSkills, name));
  }

  fs.mkdirSync(home, { recursive: true });
  syncRuntimePackage(packageRoot, path.join(home, "package"));
  installLauncher(home);
  writeRuntimeConfig(home, {
    schemaVersion: 1,
    runtimeHome: home,
    skillsDir: sharedSkills,
    node: process.execPath,
  });
  if (skillsOnly) {
    console.log("[done] skills installed; runtime skipped by request");
    return;
  }

  const [uv, uvPrefix] = await uvInvocation(home);
  const venvPython = pythonInVenv(home);
  if (!fs.existsSync(venvPython)) {
    console.log(`[runtime] creating reusable Python 3.10 environment at ${path.dirname(venvPython)}`);
    run(uv, [...uvPrefix, "venv", "--python", "3.10", path.join(home, "venv")]);
  } else {
    console.log("[runtime] reusing existing Python environment");
  }

  const pdfSkill = path.join(home, "package", "pdf-extract");
  console.log("[runtime] syncing Python dependencies");
  run(uv, [
    ...uvPrefix,
    "pip",
    "install",
    "--python",
    venvPython,
    "-e",
    pdfSkill,
    "pymupdf4llm>=0.0.17",
  ]);

  if (installModels) {
    console.log("[models] downloading or reusing cached extraction models");
    run(venvPython, [
      "-c",
      "from paper_extract import models; " +
        "print(models.get_layout_model_path()); " +
        "print(models.get_formula_det_model_path()); " +
        "print(models.get_formula_rec_model_dir()); " +
        "print(models.get_ocr_det_model_dir()); " +
        "print(models.get_ocr_rec_model_dir())",
    ], { env: { PAPER_EXTRACT_CACHE: home } });
  }

  writeRuntimeConfig(home, {
    python: venvPython,
    modelCacheRoot: home,
    modelDir: path.join(home, "models"),
  });
  console.log("[done] paper-preread is ready");
  console.log(`       run: ${path.join(process.env.PAPER_PREREAD_BIN_DIR || path.join(os.homedir(), ".local", "bin"), "paper-preread")} doctor`);
}

export async function doctor(packageRoot) {
  const home = runtimeHome();
  const config = readRuntimeConfig(home);
  const sharedSkills = process.env.PAPER_PREREAD_SKILLS_DIR || config.skillsDir || path.join(os.homedir(), ".agents", "skills");
  const python = pythonInVenv(home);
  const checks = [];
  const add = (name, ok, detail) => checks.push({ name, ok, detail });
  add("node", Number(process.versions.node.split(".")[0]) >= 18, process.version);
  add("python-runtime", fs.existsSync(python), python);
  add("paper-preread-skill", fs.existsSync(path.join(sharedSkills, "paper-preread", "SKILL.md")), path.join(sharedSkills, "paper-preread"));
  add("pdf-extract-skill", fs.existsSync(path.join(sharedSkills, "pdf-extract", "SKILL.md")), path.join(sharedSkills, "pdf-extract"));
  add("lark-cli-optional", Boolean(commandPath("lark-cli")), commandPath("lark-cli") || "not installed; Phase 6 will export a plan");
  if (fs.existsSync(python)) {
    const result = run(python, ["-c", "import fitz,pymupdf4llm,paper_extract; print('ok')"], { capture: true });
    add("python-packages", result.status === 0, result.status === 0 ? "imports OK" : result.stderr.trim());
  } else {
    add("python-packages", false, "runtime missing");
  }
  const modelDir = path.join(home, "models");
  add("models", fs.existsSync(modelDir) && fs.readdirSync(modelDir).length > 0, modelDir);
  return {
    ready: checks.filter((item) => item.name !== "lark-cli-optional").every((item) => item.ok),
    packageRoot,
    runtimeHome: home,
    checks,
  };
}

export function printDoctor(result) {
  for (const check of result.checks) {
    console.log(`${check.ok ? "✓" : "✗"} ${check.name}: ${check.detail}`);
  }
  console.log(result.ready ? "Ready" : "Not ready; run `paper-preread install`");
}

export async function runPdfExtract(args) {
  if (!args.length) {
    console.error("Usage: paper-preread extract <paper.pdf> --out <dir> [options]");
    return 2;
  }
  const home = runtimeHome();
  const python = pythonInVenv(home);
  if (!fs.existsSync(python)) {
    console.error("Runtime missing. Run `paper-preread install` first.");
    return 1;
  }
  const result = spawnSync(python, ["-m", "paper_extract.cli", ...args], {
    stdio: "inherit",
    env: { ...process.env, PAPER_EXTRACT_CACHE: home },
  });
  return result.status ?? 1;
}

function optionValue(args, name) {
  const index = args.indexOf(name);
  return index >= 0 && index + 1 < args.length ? args[index + 1] : "";
}

export async function runPrepare(packageRoot, args) {
  const arxivId = args[0] && !args[0].startsWith("-") ? args[0] : "";
  const outValue = optionValue(args, "--out");
  if (!arxivId || !outValue) {
    console.error("Usage: paper-preread prepare <arxiv-id> --out <dir> [--with-formulas]");
    return 2;
  }
  const outDir = path.resolve(outValue);
  fs.mkdirSync(outDir, { recursive: true });
  const home = runtimeHome();
  const python = pythonInVenv(home);
  if (!fs.existsSync(python)) {
    console.error("Runtime missing. Run `paper-preread install` first.");
    return 1;
  }
  const installedSkill = path.join(home, "package", "paper-preread");
  const skill = fs.existsSync(installedSkill) ? installedSkill : path.join(packageRoot, "paper-preread");
  const script = (name) => path.join(skill, "scripts", name);
  const modelEnv = { PAPER_EXTRACT_CACHE: home };
  const steps = [
    ["download PDF", [script("download_arxiv_pdf.py"), arxivId, outDir]],
    ["extract figures and tables", ["-m", "paper_extract.cli", path.join(outDir, "paper.pdf"), "--out", outDir, ...(args.includes("--with-formulas") ? [] : ["--no-formulas"])]],
    ["extract fallback Markdown", [script("extract_pdf_text.py"), path.join(outDir, "paper.pdf"), outDir]],
    ["parse ar5iv metadata", [script("parse_ar5iv.py"), arxivId, outDir]],
    ["parse structured paper", [script("parse_ar5iv_extended.py"), arxivId, outDir]],
    ["build figure aliases", [script("build_figure_alias.py"), outDir]],
    ["build shared context", [script("build_paper_context.py"), outDir]],
  ];
  for (const [label, stepArgs] of steps) {
    console.log(`[prepare] ${label}`);
    const result = spawnSync(python, stepArgs, {
      stdio: "inherit",
      cwd: outDir,
      env: { ...process.env, ...modelEnv },
    });
    if (result.status !== 0) return result.status ?? 1;
  }
  console.log(`[done] Phase 2 outputs: ${outDir}`);
  return 0;
}

export async function runPhase6(packageRoot, args) {
  const home = runtimeHome();
  const installedScript = path.join(home, "package", "paper-preread", "scripts", "phase6_write.py");
  const sourceScript = path.join(packageRoot, "paper-preread", "scripts", "phase6_write.py");
  const script = fs.existsSync(installedScript) ? installedScript : sourceScript;
  const python = fs.existsSync(pythonInVenv(home)) ? pythonInVenv(home) : commandPath("python3");
  if (!python) {
    console.error("Python 3 is required for Phase 6");
    return 1;
  }
  const result = spawnSync(python, [script, ...args], { stdio: "inherit" });
  return result.status ?? 1;
}
