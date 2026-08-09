#!/usr/bin/env node
// Runs the per-sector Python artifact builders concurrently.
//
// Output is streamed live (prefixed per sector) rather than buffered until
// each child exits -- with ~10 builders running at once and one of them
// (commercial aerospace) sequentially hitting a dozen external live sources,
// buffered output meant total silence for however long the slowest builder
// took, indistinguishable from a genuine hang. Each builder also gets a hard
// timeout so one stuck process can't block the whole run forever.

import { spawn } from "node:child_process";
import fs from "node:fs";
import path from "node:path";

import { appRoot as projectRoot, LIVE_SECTORS } from "./sectors.mjs";
import { protectArtifactRefresh } from "./artifact-refresh-guard.mjs";

const pythonBin = process.env.PYTHON_BIN || "python3";
const tolerateErrors = process.argv.includes("--tolerate-errors");
const BUILDER_TIMEOUT_MS = Number(process.env.BUILDER_TIMEOUT_MS) || 10 * 60 * 1000;
const KILL_GRACE_MS = 5000;

const BUILDERS = LIVE_SECTORS.map((sector) => ({
  id: sector.id,
  script: sector.builder,
  output: sector.artifact,
  statusOutput: sector.statusOutput,
}));

const previousStates = new Map(
  BUILDERS.map((builder) => {
    const artifactPath = path.join(projectRoot, builder.output);
    const statusPath = path.join(projectRoot, builder.statusOutput);
    return [builder.id, {
      artifactPath,
      statusPath,
      previousArtifactBytes: fs.existsSync(artifactPath) ? fs.readFileSync(artifactPath) : null,
      previousStatusBytes: fs.existsSync(statusPath) ? fs.readFileSync(statusPath) : null,
    }];
  }),
);

// Prefixes each complete line as it arrives; a trailing partial line is held
// back and flushed (unprefixed content never lost) when the stream ends.
function makeLineStreamer(prefix, target) {
  let buffer = "";
  return {
    write(chunk) {
      buffer += chunk;
      const lines = buffer.split("\n");
      buffer = lines.pop();
      for (const line of lines) {
        target.write(`${prefix} ${line}\n`);
      }
    },
    flush() {
      if (buffer) {
        target.write(`${prefix} ${buffer}\n`);
        buffer = "";
      }
    },
  };
}

function runBuilder({ id, script, output, statusOutput }) {
  return new Promise((resolvePromise) => {
    const args = [script, "--output", output, "--status-output", statusOutput];
    const child = spawn(pythonBin, args, { cwd: projectRoot, stdio: ["ignore", "pipe", "pipe"] });
    const prefix = `[${id}]`;
    const outStreamer = makeLineStreamer(prefix, process.stdout);
    const errStreamer = makeLineStreamer(prefix, process.stderr);
    let settled = false;
    let timedOut = false;

    const timer = setTimeout(() => {
      timedOut = true;
      process.stderr.write(`${prefix} exceeded ${BUILDER_TIMEOUT_MS}ms timeout, sending SIGTERM\n`);
      child.kill("SIGTERM");
      setTimeout(() => {
        if (!settled) child.kill("SIGKILL");
      }, KILL_GRACE_MS);
    }, BUILDER_TIMEOUT_MS);

    child.stdout.on("data", (chunk) => outStreamer.write(chunk.toString()));
    child.stderr.on("data", (chunk) => errStreamer.write(chunk.toString()));

    const finish = (code) => {
      if (settled) return;
      settled = true;
      clearTimeout(timer);
      outStreamer.flush();
      errStreamer.flush();
      resolvePromise({ id, script, code: timedOut ? 124 : code, timedOut });
    };

    child.on("close", finish);
    child.on("error", (error) => {
      if (settled) return;
      errStreamer.write(error.message);
      finish(1);
    });
  });
}

const results = await Promise.all(BUILDERS.map(runBuilder));

let hasFailure = false;
for (const result of results) {
  const previous = previousStates.get(result.id);
  if (previous) {
    protectArtifactRefresh(previous);
  }
  if (result.code !== 0) {
    hasFailure = true;
    const reason = result.timedOut ? `timed out after ${BUILDER_TIMEOUT_MS}ms` : `exited with code ${result.code}`;
    process.stderr.write(`[run-artifact-builders] ${result.script} ${reason}\n`);
  }
}

if (hasFailure && !tolerateErrors) {
  process.exit(1);
}
process.exit(0);
