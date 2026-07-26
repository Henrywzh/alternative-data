#!/usr/bin/env node
// Runs the per-sector Python artifact builders concurrently.

import { spawn } from "node:child_process";

import { appRoot as projectRoot, LIVE_SECTORS } from "./sectors.mjs";

const pythonBin = process.env.PYTHON_BIN || "python3";
const tolerateErrors = process.argv.includes("--tolerate-errors");

const BUILDERS = LIVE_SECTORS.map((sector) => ({
  script: sector.builder,
  output: sector.artifact,
  statusOutput: sector.statusOutput,
}));

function runBuilder({ script, output, statusOutput }) {
  return new Promise((resolvePromise) => {
    const args = [script, "--output", output, "--status-output", statusOutput];
    const child = spawn(pythonBin, args, { cwd: projectRoot, stdio: ["ignore", "pipe", "pipe"] });
    let stdout = "";
    let stderr = "";
    child.stdout.on("data", (chunk) => { stdout += chunk; });
    child.stderr.on("data", (chunk) => { stderr += chunk; });
    child.on("close", (code) => {
      resolvePromise({ script, code, stdout, stderr });
    });
    child.on("error", (error) => {
      resolvePromise({ script, code: 1, stdout, stderr: `${stderr}\n${error.message}` });
    });
  });
}

const results = await Promise.all(BUILDERS.map(runBuilder));

let hasFailure = false;
for (const result of results) {
  if (result.stdout) process.stdout.write(result.stdout);
  if (result.stderr) process.stderr.write(result.stderr);
  if (result.code !== 0) {
    hasFailure = true;
    process.stderr.write(`[run-artifact-builders] ${result.script} exited with code ${result.code}\n`);
  }
}

if (hasFailure && !tolerateErrors) {
  process.exit(1);
}
process.exit(0);
