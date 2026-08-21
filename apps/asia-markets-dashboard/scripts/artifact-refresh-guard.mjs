import fs from "node:fs";

/**
 * Find destructive refreshes without rejecting legitimate structural changes.
 *
 * A source outage is allowed to produce an empty in-memory frame, but it must
 * not replace a previously published non-empty dataset.  Deliberate removal of
 * a dataset remains possible when the old and new artifacts both contain
 * non-empty data; this guard is specifically for the silent empty-snapshot
 * failure mode.
 */
export function findEmptyDatasetRegressions(previousArtifact, currentArtifact) {
  const previousDatasets = previousArtifact?.snapshot?.datasets;
  const currentDatasets = currentArtifact?.snapshot?.datasets;
  if (!previousDatasets || !currentDatasets) return [];

  return Object.entries(previousDatasets)
    .filter(([, rows]) => Array.isArray(rows) && rows.length > 0)
    .filter(([datasetId]) => (
      currentDatasets[datasetId] === undefined
      || (Array.isArray(currentDatasets[datasetId]) && currentDatasets[datasetId].length === 0)
    ))
    .map(([datasetId, rows]) => ({
      datasetId,
      previousRows: rows.length,
      currentRows: currentDatasets[datasetId] === undefined ? null : currentDatasets[datasetId].length,
      missing: currentDatasets[datasetId] === undefined,
    }));
}

/**
 * Fields that carry a dataset's observation period, most specific first.
 * Only an exact key match counts -- "period_change" and "date_semantics" are
 * labels, not observation dates.
 */
const OBSERVATION_DATE_FIELDS = [
  "observation_date",
  "date",
  "usage_date",
  "period",
  "quarter",
  "as_of_date",
];

const ISO_DATE_PREFIX = /^\d{4}-\d{2}(-\d{2})?$/;

function maxObservationDate(rows, field) {
  let max = null;
  for (const row of rows) {
    if (!row || typeof row !== "object") continue;
    const value = row[field];
    if (typeof value !== "string" || !ISO_DATE_PREFIX.test(value)) continue;
    if (max === null || value > max) max = value;
  }
  return max;
}

/**
 * Find datasets whose newest observation moved BACKWARDS across a refresh.
 *
 * The empty-dataset check above only catches a total wipe.  It cannot see a
 * source quietly serving an older vintage: build f97e0672 (2026-08-20) rolled
 * three published HKMA series from 2026-06 back to 2026-05 with every row
 * count still healthy, and shipped.  A published series losing its newest
 * period is an upstream or cache fault in every case seen so far -- real
 * corrections revise values in place, they do not retract a month.
 *
 * Deliberately conservative: both sides must be non-empty, must agree on
 * which field carries the observation period, and must both parse as ISO
 * dates of the same shape.  Anything else is left alone.
 */
export function findStaleDatasetRegressions(previousArtifact, currentArtifact) {
  const previousDatasets = previousArtifact?.snapshot?.datasets;
  const currentDatasets = currentArtifact?.snapshot?.datasets;
  if (!previousDatasets || !currentDatasets) return [];

  const regressions = [];
  for (const [datasetId, previousRows] of Object.entries(previousDatasets)) {
    const currentRows = currentDatasets[datasetId];
    if (!Array.isArray(previousRows) || previousRows.length === 0) continue;
    if (!Array.isArray(currentRows) || currentRows.length === 0) continue;

    const sample = previousRows.find((row) => row && typeof row === "object");
    const currentSample = currentRows.find((row) => row && typeof row === "object");
    if (!sample || !currentSample) continue;
    const field = OBSERVATION_DATE_FIELDS.find(
      (candidate) => candidate in sample && candidate in currentSample,
    );
    if (!field) continue;

    const previousMax = maxObservationDate(previousRows, field);
    const currentMax = maxObservationDate(currentRows, field);
    if (previousMax === null || currentMax === null) continue;
    // "2026-06" and "2026-06-30" are not comparable as strings.
    if (previousMax.length !== currentMax.length) continue;
    if (currentMax >= previousMax) continue;

    regressions.push({ datasetId, field, previousLatest: previousMax, currentLatest: currentMax });
  }
  return regressions;
}

export function protectArtifactRefresh({
  artifactPath,
  statusPath,
  previousArtifactBytes,
  previousStatusBytes,
  log = (message) => process.stderr.write(`${message}\n`),
}) {
  if (!previousArtifactBytes) {
    return { protected: false, reason: null, regressions: [] };
  }

  if (!fs.existsSync(artifactPath)) {
    fs.writeFileSync(artifactPath, previousArtifactBytes);
    if (previousStatusBytes && statusPath) fs.writeFileSync(statusPath, previousStatusBytes);
    log(`[artifact-refresh-guard] restored missing artifact: ${artifactPath}`);
    return { protected: true, reason: "missing-artifact", regressions: [] };
  }

  let previousArtifact;
  let currentArtifact;
  try {
    previousArtifact = JSON.parse(previousArtifactBytes.toString("utf8"));
    currentArtifact = JSON.parse(fs.readFileSync(artifactPath, "utf8"));
  } catch (error) {
    fs.writeFileSync(artifactPath, previousArtifactBytes);
    if (previousStatusBytes && statusPath) fs.writeFileSync(statusPath, previousStatusBytes);
    log(`[artifact-refresh-guard] preserved previous artifact after invalid JSON: ${artifactPath} (${error.message})`);
    return { protected: true, reason: "invalid-json", regressions: [] };
  }

  const regressions = findEmptyDatasetRegressions(previousArtifact, currentArtifact);
  if (regressions.length > 0) {
    fs.writeFileSync(artifactPath, previousArtifactBytes);
    if (previousStatusBytes && statusPath) fs.writeFileSync(statusPath, previousStatusBytes);
    const detail = regressions
      .map((item) => `${item.datasetId} ${item.previousRows}->${item.missing ? "missing" : "0"}`)
      .join(", ");
    log(`[artifact-refresh-guard] preserved previous artifact for ${artifactPath}: ${detail}`);
    return { protected: true, reason: "empty-dataset-regression", regressions };
  }

  const staleRegressions = findStaleDatasetRegressions(previousArtifact, currentArtifact);
  if (staleRegressions.length > 0) {
    fs.writeFileSync(artifactPath, previousArtifactBytes);
    if (previousStatusBytes && statusPath) fs.writeFileSync(statusPath, previousStatusBytes);
    const detail = staleRegressions
      .map((item) => `${item.datasetId} ${item.previousLatest}->${item.currentLatest}`)
      .join(", ");
    log(`[artifact-refresh-guard] preserved previous artifact for ${artifactPath}: ${detail}`);
    return { protected: true, reason: "stale-dataset-regression", regressions: staleRegressions };
  }

  return { protected: false, reason: null, regressions: [] };
}
