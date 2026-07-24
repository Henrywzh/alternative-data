#!/usr/bin/env node
// Runs the per-sector Python artifact builders concurrently.

import { spawn } from "node:child_process";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const projectRoot = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const pythonBin = process.env.PYTHON_BIN || "python3";
const tolerateErrors = process.argv.includes("--tolerate-errors");

const BUILDERS = [
  { script: "scripts/build_hk_real_estate_artifact.py", output: ".generated/hk-real-estate-artifact.json", statusOutput: "src/data/dashboard-status.json" },
  { script: "scripts/build_hk_local_consumer_artifact.py", output: ".generated/hk-local-consumer-artifact.json", statusOutput: "src/data/dashboard-status-hk-local-consumer.json" },
  { script: "scripts/build_hk_utilities_artifact.py", output: ".generated/hk-utilities-artifact.json", statusOutput: "src/data/dashboard-status-hk-utilities.json" },
  { script: "scripts/build_hk_transport_artifact.py", output: ".generated/hk-transport-artifact.json", statusOutput: "src/data/dashboard-status-hk-transport.json" },
  { script: "scripts/build_hk_telecom_artifact.py", output: ".generated/hk-telecom-artifact.json", statusOutput: "src/data/dashboard-status-hk-telecom.json" },
  { script: "scripts/build_hk_reit_artifact.py", output: ".generated/hk-reit-artifact.json", statusOutput: "src/data/dashboard-status-hk-reit.json" },
];

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
