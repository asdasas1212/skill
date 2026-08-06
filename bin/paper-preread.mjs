#!/usr/bin/env node
import { fileURLToPath } from "node:url";
import fs from "node:fs";
import path from "node:path";
import process from "node:process";
import {
  doctor,
  install,
  printDoctor,
  runPrepare,
  runPhase6,
  runPdfExtract,
} from "../lib/commands.mjs";

const packageRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

function usage() {
  console.log(`paper-preread CLI

Usage:
  paper-preread install [--skip-models] [--skills-only]
  paper-preread doctor [--json]
  paper-preread prepare <arxiv-id> --out <dir> [--with-formulas]
  paper-preread extract <paper.pdf> --out <dir> [paper-extract options]
  paper-preread phase6 --out-dir <dir> [--parent <wiki-url-or-token>] [--profile <name|auto>] [--title <title>] [--commit]
  paper-preread version

The persistent runtime lives in PAPER_PREREAD_HOME or ~/.paper-preread.
phase6 is safe by default: without --commit it only writes an export plan.`);
}

function has(args, flag) {
  return args.includes(flag);
}

async function main() {
  const [command = "help", ...args] = process.argv.slice(2);
  if (command === "help" || command === "--help" || command === "-h") {
    usage();
    return;
  }
  if (command === "version" || command === "--version" || command === "-v") {
    const packageDoc = JSON.parse(fs.readFileSync(path.join(packageRoot, "package.json"), "utf8"));
    console.log(packageDoc.version);
    return;
  }
  if (command === "install") {
    await install(packageRoot, {
      installModels: !has(args, "--skip-models"),
      skillsOnly: has(args, "--skills-only"),
    });
    return;
  }
  if (command === "doctor") {
    const result = await doctor(packageRoot);
    if (has(args, "--json")) console.log(JSON.stringify(result, null, 2));
    else printDoctor(result);
    process.exitCode = result.ready ? 0 : 1;
    return;
  }
  if (command === "extract") {
    process.exitCode = await runPdfExtract(args);
    return;
  }
  if (command === "prepare") {
    process.exitCode = await runPrepare(packageRoot, args);
    return;
  }
  if (command === "phase6") {
    process.exitCode = await runPhase6(packageRoot, args);
    return;
  }
  console.error(`Unknown command: ${command}`);
  usage();
  process.exitCode = 2;
}

main().catch((error) => {
  console.error(`paper-preread: ${error.message}`);
  process.exitCode = 1;
});
