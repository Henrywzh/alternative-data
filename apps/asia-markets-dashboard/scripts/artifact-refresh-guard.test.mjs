import assert from "node:assert/strict";
import fs from "node:fs";
import os from "node:os";
import path from "node:path";
import test from "node:test";

import {
  findEmptyDatasetRegressions,
  findStaleDatasetRegressions,
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

test("detects a published series losing its newest period", () => {
  // The f97e0672 shape: full row counts, one month retracted.
  const previous = {
    snapshot: { datasets: { hkma_mortgage_activity: [{ date: "2026-05" }, { date: "2026-06" }] } },
  };
  const current = {
    snapshot: { datasets: { hkma_mortgage_activity: [{ date: "2026-04" }, { date: "2026-05" }] } },
  };
  assert.deepEqual(findStaleDatasetRegressions(previous, current), [
    {
      datasetId: "hkma_mortgage_activity",
      field: "date",
      previousLatest: "2026-06",
      currentLatest: "2026-05",
    },
  ]);
});

test("does not block a refresh that advances or holds its newest period", () => {
  const previous = {
    snapshot: {
      datasets: {
        advancing: [{ date: "2026-05" }],
        unchanged: [{ date: "2026-05" }],
        // Fewer rows but a newer period: the SHKP quarterly extractor churns
        // row counts between builds while moving forward.
        shrinking: [{ date: "2026-03-31" }, { date: "2026-03-31" }, { date: "2026-03-31" }],
      },
    },
  };
  const current = {
    snapshot: {
      datasets: {
        advancing: [{ date: "2026-06" }],
        unchanged: [{ date: "2026-05" }],
        shrinking: [{ date: "2026-06-30" }],
      },
    },
  };
  assert.deepEqual(findStaleDatasetRegressions(previous, current), []);
});

test("leaves datasets it cannot compare alone", () => {
  const previous = {
    snapshot: {
      datasets: {
        // No observation-period field: "period_change" is a label.
        labelled: [{ period_change: "up", value: 2 }],
        // Mixed granularity is not string-comparable.
        mixed: [{ date: "2026-06-30" }],
        // An empty current side is the other guard's job, not this one's.
        emptied: [{ date: "2026-06" }],
      },
    },
  };
  const current = {
    snapshot: {
      datasets: {
        labelled: [{ period_change: "down", value: 1 }],
        mixed: [{ date: "2026-05" }],
        emptied: [],
      },
    },
  };
  assert.deepEqual(findStaleDatasetRegressions(previous, current), []);
});

test("restores the previous artifact after a stale-vintage regression", () => {
  const root = fs.mkdtempSync(path.join(os.tmpdir(), "artifact-refresh-guard-stale-"));
  const artifactPath = path.join(root, "artifact.json");
  const statusPath = path.join(root, "status.json");
  const previousArtifactBytes = Buffer.from(
    JSON.stringify({ snapshot: { datasets: { history: [{ date: "2026-06" }] } } }),
  );
  const previousStatusBytes = Buffer.from(JSON.stringify({ status: "Healthy" }));
  fs.writeFileSync(
    artifactPath,
    JSON.stringify({ snapshot: { datasets: { history: [{ date: "2026-05" }] } } }),
  );
  fs.writeFileSync(statusPath, JSON.stringify({ status: "Stale" }));

  const result = protectArtifactRefresh({
    artifactPath,
    statusPath,
    previousArtifactBytes,
    previousStatusBytes,
    log: () => {},
  });

  assert.equal(result.protected, true);
  assert.equal(result.reason, "stale-dataset-regression");
  assert.deepEqual(JSON.parse(fs.readFileSync(artifactPath, "utf8")), {
    snapshot: { datasets: { history: [{ date: "2026-06" }] } },
  });
  assert.deepEqual(JSON.parse(fs.readFileSync(statusPath, "utf8")), { status: "Healthy" });
});
