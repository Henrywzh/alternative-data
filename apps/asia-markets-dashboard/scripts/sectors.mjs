// Loader for the sector roster in ../sectors.json.
//
// Every field the build pipeline needs about a sector is derived here rather
// than restated per script, so run-artifact-builders / build-static-hub /
// package-dashboard cannot disagree about which sectors exist. sectors.json is
// plain JSON (not .mjs) so tests/test_asia_markets_wiring.py can read the same
// roster from Python without shelling out to node.

import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

export const appRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

const roster = JSON.parse(fs.readFileSync(path.join(appRoot, "sectors.json"), "utf8"));

// Paths that are a pure function of the sector id live here, not in sectors.json,
// so a typo cannot make the artifact and the route disagree.
export const LIVE_SECTORS = roster.live.map((sector) => ({
  ...sector,
  artifact: `.generated/${sector.id}-artifact.json`,
  statusOutput: `src/data/${sector.statusFile}`,
  route: `sectors/${sector.id}`,
}));

export const PLANNED_SECTORS = roster.planned;

export const readStatus = (sector) =>
  JSON.parse(fs.readFileSync(path.join(appRoot, "src", "data", sector.statusFile), "utf8"));

// Downloadable export filenames. build-static-hub writes the links and
// package-dashboard writes the files, so both must derive the names here --
// when they each derived their own, the ZH links pointed at files that were
// never written, and hk-reit (whose attachment_filename is "hk-reit-monitor.html"
// rather than "<id>-dashboard-<date>.html") additionally produced the mangled
// name "hk-reit-dashboard-zh-hk-reit-monitor.html". Suffixing before the
// extension is shape-independent, so a sector that names its attachment
// differently still gets a valid pair.
export function attachmentNames(sector, status) {
  const en = status.attachment_filename || `${sector.id}-monitor.html`;
  const dot = en.lastIndexOf(".");
  const zh = dot === -1 ? `${en}-zh` : `${en.slice(0, dot)}-zh${en.slice(dot)}`;
  return { en, zh };
}
