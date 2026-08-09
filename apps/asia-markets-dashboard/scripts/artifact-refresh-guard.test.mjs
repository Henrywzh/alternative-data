import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  findEmptyDatasetRegressions,
  protectArtifactRefresh,
} from "./artifact-refresh-guard.mjs";

test("detects a non-empty dataset being refreshed to empty", () => {
  const previous = { snapshot: { datasets: { history: [{ date: "2026-01" }] } } };
  const current = { snapshot: { datasets: { history: [] } } };
  assert.deepEqual(findEmptyDatasetRegressions(previous, current), [
    { datasetId: "history", previousRows: 1, currentRows: 0, missing: false },
  ]);
});

test("does not block a non-empty refresh or an already-empty dataset", () => {
  const previous = { snapshot: { datasets: { history: [{ date: "2026-01" }], optional: [] } } };
  const current = { snapshot: { datasets: { history: [{ date: "2026-02" }], optional: [] } } };
  assert.deepEqual(findEmptyDatasetRegressions(previous, current), []);
});

test("treats a previously published dataset disappearing as destructive", () => {
  const previous = { snapshot: { datasets: { history: [{ date: "2026-01" }] } } };
  const current = { snapshot: { datasets: {} } };
  assert.deepEqual(findEmptyDatasetRegressions(previous, current), [
    { datasetId: "history", previousRows: 1, currentRows: null, missing: true },
  ]);
});

test("restores both artifact and status after an empty regression", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "artifact-refresh-guard-"));
  const artifactPath = path.join(root, "artifact.json");
  const statusPath = path.join(root, "status.json");
  const previousArtifactBytes = Buffer.from(JSON.stringify({ snapshot: { datasets: { history: [{ value: 1 }] } } }));
  const previousStatusBytes = Buffer.from(JSON.stringify({ status: "Healthy" }));
  fs.writeFileSync(artifactPath, JSON.stringify({ snapshot: { datasets: { history: [] } } }));
  fs.writeFileSync(statusPath, JSON.stringify({ status: "Healthy" }));

  const result = protectArtifactRefresh({
    artifactPath,
    statusPath,
    previousArtifactBytes,
    previousStatusBytes,
    log: () => {},
  });

  assert.equal(result.protected, true);
  assert.deepEqual(JSON.parse(fs.readFileSync(artifactPath, "utf8")), JSON.parse(previousArtifactBytes));
  assert.deepEqual(JSON.parse(fs.readFileSync(statusPath, "utf8")), JSON.parse(previousStatusBytes));
});

test("restores a missing artifact without touching another sector", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "artifact-refresh-guard-missing-"));
  const artifactPath = path.join(root, "artifact.json");
  const statusPath = path.join(root, "status.json");
  const previousArtifactBytes = Buffer.from(JSON.stringify({ snapshot: { datasets: { history: [{ value: 1 }] } } }));
  const previousStatusBytes = Buffer.from(JSON.stringify({ status: "Healthy" }));

  const result = protectArtifactRefresh({
    artifactPath,
    statusPath,
    previousArtifactBytes,
    previousStatusBytes,
    log: () => {},
  });

  assert.equal(result.reason, "missing-artifact");
  assert.deepEqual(JSON.parse(fs.readFileSync(artifactPath, "utf8")), JSON.parse(previousArtifactBytes));
  assert.deepEqual(JSON.parse(fs.readFileSync(statusPath, "utf8")), JSON.parse(previousStatusBytes));
});
