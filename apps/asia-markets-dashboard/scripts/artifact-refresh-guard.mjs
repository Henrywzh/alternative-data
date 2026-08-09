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
  if (regressions.length === 0) {
    return { protected: false, reason: null, regressions: [] };
  }

  fs.writeFileSync(artifactPath, previousArtifactBytes);
  if (previousStatusBytes && statusPath) fs.writeFileSync(statusPath, previousStatusBytes);
  const detail = regressions
    .map((item) => `${item.datasetId} ${item.previousRows}->${item.missing ? "missing" : "0"}`)
    .join(", ");
  log(`[artifact-refresh-guard] preserved previous artifact for ${artifactPath}: ${detail}`);
  return { protected: true, reason: "empty-dataset-regression", regressions };
}
