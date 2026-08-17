"""Detect Cloudflare dashboard changes that deserve a Streamlit parity review.

The daily dashboard refresh changes many JSON values without changing the
artifact contract. This checker compares manifest/source/dataset structure and
only raises a reminder for structural or pipeline changes.
"""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from pathlib import Path
from typing import Any


REPO_ROOT = Path(__file__).resolve().parents[3]
PROTOCOL_PATH = "docs/asia-markets/STREAMLIT_PARITY_PROTOCOL.md"
ARTIFACT_RE = re.compile(r"\.generated/([^/]+?)-artifact(?:-zh)?\.json$")
CODE_SUFFIXES = {".js", ".mjs", ".py", ".json"}


def git(*args: str) -> str:
    result = subprocess.run(
        ["git", *args],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        raise RuntimeError(result.stderr.strip() or f"git {' '.join(args)} failed")
    return result.stdout


def read_ref(ref: str | None, path: str) -> str | None:
    if not ref or set(ref) == {"0"}:
        return None
    result = subprocess.run(
        ["git", "show", f"{ref}:{path}"],
        cwd=REPO_ROOT,
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout if result.returncode == 0 else None


def json_ref(ref: str | None, path: str) -> dict[str, Any] | None:
    raw = read_ref(ref, path)
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def artifact_contract(payload: dict[str, Any] | None) -> dict[str, Any] | None:
    if payload is None:
        return None
    manifest = payload.get("manifest", {})
    snapshot = payload.get("snapshot", {})

    def manifest_items(kind: str) -> list[dict[str, Any]]:
        items = manifest.get(kind, []) if isinstance(manifest, dict) else []
        return sorted(
            [item for item in items if isinstance(item, dict)],
            key=lambda item: str(item.get("id", "")),
        )

    datasets = snapshot.get("datasets", {}) if isinstance(snapshot, dict) else {}
    sources = payload.get("sources", [])
    return {
        "cards": manifest_items("cards"),
        "charts": manifest_items("charts"),
        "tables": manifest_items("tables"),
        "datasets": sorted(datasets) if isinstance(datasets, dict) else [],
        "sources": sorted(
            [source for source in sources if isinstance(source, dict)],
            key=lambda source: str(source.get("id", "")),
        ),
    }


def is_artifact_path(path: str) -> bool:
    return path.startswith("apps/asia-markets-dashboard/.generated/") and bool(ARTIFACT_RE.search(path))


def artifact_sector(path: str) -> str | None:
    match = ARTIFACT_RE.search(path)
    return match.group(1) if match else None


def changed_paths(base: str | None, head: str) -> list[str]:
    if base and set(base) != {"0"}:
        output = git("diff", "--name-only", base, head, "--")
    else:
        output = git("diff-tree", "--root", "--no-commit-id", "--name-only", "-r", head)
    return sorted({line.strip() for line in output.splitlines() if line.strip()})


def add_reason(reasons: list[str], reason: str) -> None:
    if reason not in reasons:
        reasons.append(reason)


def assess_changes(
    paths: list[str],
    before_contracts: dict[str, dict[str, Any] | None],
    after_contracts: dict[str, dict[str, Any] | None],
) -> dict[str, Any]:
    reasons: list[str] = []
    affected: set[str] = set()
    structural_artifacts: list[str] = []

    for path in paths:
        if path == PROTOCOL_PATH:
            continue
        if path.endswith("apps/asia-markets-dashboard/sectors.json"):
            add_reason(reasons, "sector roster changed")
            continue
        if is_artifact_path(path):
            sector = artifact_sector(path)
            if sector:
                affected.add(sector)
            if before_contracts.get(path) != after_contracts.get(path):
                structural_artifacts.append(path)
            continue
        if path.startswith("apps/asia-markets-dashboard/scripts/") and Path(path).suffix in CODE_SUFFIXES:
            add_reason(reasons, "Cloudflare builder or packaging code changed")
            continue
        if path.startswith("apps/asia-markets-dashboard/src/") and "src/data/" not in path:
            add_reason(reasons, "Cloudflare dashboard UI code changed")
            continue
        if path.startswith("src/hk_") or path.startswith("src/asia_"):
            add_reason(reasons, "shared Hong Kong/Asia source pipeline changed")

    if structural_artifacts:
        add_reason(reasons, "Cloudflare artifact contract changed")
        for path in structural_artifacts:
            sector = artifact_sector(path)
            if sector:
                affected.add(sector)

    return {
        "needs_review": bool(reasons),
        "reasons": reasons,
        "affected": sorted(affected),
        "structural_artifacts": structural_artifacts,
        "changed_paths": paths,
    }


def report_markdown(assessment: dict[str, Any]) -> str:
    marker = "<!-- streamlit-parity-reminder -->"
    if not assessment["needs_review"]:
        return (
            f"{marker}\n"
            "## Streamlit parity\n\n"
            "✅ No structural Cloudflare dashboard change detected in this diff; "
            "value-only refreshes do not require a Streamlit parity decision."
        )

    affected = ", ".join(assessment["affected"]) or "Cloudflare dashboard pipeline"
    lines = [
        marker,
        "## Streamlit parity review required",
        "",
        f"Cloudflare changes may affect Streamlit research coverage: **{affected}**.",
        "",
        "Reasons:",
    ]
    lines.extend(f"- {reason}" for reason in assessment["reasons"])
    if assessment["structural_artifacts"]:
        lines.append("")
        lines.append("Structural artifact changes:")
        lines.extend(f"- {path}" for path in assessment["structural_artifacts"])
    lines.extend(
        [
            "",
            "Review docs/asia-markets/STREAMLIT_PARITY_PROTOCOL.md and decide:",
            "- Streamlit now",
            "- Streamlit later after more history/quality checks",
            "- Cloudflare only",
            "- blocked/not suitable",
        ]
    )
    return "\n".join(lines)


def write_outputs(assessment: dict[str, Any], report: str, summary_file: str | None, github_output: str | None) -> None:
    if summary_file:
        with Path(summary_file).open("a", encoding="utf-8") as handle:
            handle.write(report + "\n")
    if github_output:
        with Path(github_output).open("a", encoding="utf-8") as handle:
            handle.write(f"needs_review={'true' if assessment['needs_review'] else 'false'}\n")
            handle.write("comment<<STREAMLIT_PARITY_EOF\n")
            handle.write(report + "\n")
            handle.write("STREAMLIT_PARITY_EOF\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--base", default="")
    parser.add_argument("--head", required=True)
    parser.add_argument("--summary-file")
    parser.add_argument("--github-output")
    args = parser.parse_args()

    paths = changed_paths(args.base, args.head)
    before_contracts = {
        path: artifact_contract(json_ref(args.base, path))
        for path in paths
        if is_artifact_path(path)
    }
    after_contracts = {
        path: artifact_contract(json_ref(args.head, path))
        for path in paths
        if is_artifact_path(path)
    }
    assessment = assess_changes(paths, before_contracts, after_contracts)
    report = report_markdown(assessment)
    write_outputs(assessment, report, args.summary_file, args.github_output)
    print(report)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

