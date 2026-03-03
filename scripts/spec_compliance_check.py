#!/usr/bin/env python3
"""Spec compliance checker — scans test files for FR/NFR coverage."""
from __future__ import annotations

import argparse
import re
import sys
from datetime import date
from pathlib import Path

SPEC_FILE = Path("specs/001-knowledge-ai-agent/spec.md")
TESTS_DIR = Path("backend/tests")
E2E_TESTS_DIR = Path("frontend/tests")
WAIVERS = {"NFR-001", "NFR-009"}


def extract_requirements(spec_path: Path) -> list[str]:
    """Extract all FR-NNN and NFR-NNN identifiers from spec."""
    text = spec_path.read_text(encoding="utf-8")
    pattern = re.compile(r"\b((?:FR|NFR)-\d{3})\b")
    found = sorted(set(pattern.findall(text)))
    return found


def scan_covered(tests_dir: Path, e2e_dir: Path) -> set[str]:
    """Scan test files for requirement ID references."""
    covered: set[str] = set()
    pattern = re.compile(r"\b((?:FR|NFR)-\d{3})\b")
    dirs = [d for d in [tests_dir, e2e_dir] if d.exists()]
    for d in dirs:
        for ext in ("*.py", "*.ts", "*.spec.ts"):
            for f in d.rglob(ext):
                text = f.read_text(encoding="utf-8", errors="ignore")
                covered.update(pattern.findall(text))
    return covered


def write_report(
    output_path: Path,
    all_reqs: list[str],
    covered: set[str],
    waivers: set[str],
) -> tuple[int, int]:
    """Write markdown compliance report. Returns (covered_count, uncovered_count)."""
    covered_reqs = [r for r in all_reqs if r in covered]
    waived_reqs = [r for r in all_reqs if r in waivers]
    uncovered_reqs = [r for r in all_reqs if r not in covered and r not in waivers]

    lines = [
        "# Spec Compliance Report",
        "",
        f"Generated: {date.today().isoformat()}",
        "",
        "## Summary",
        "",
        "| Metric | Count |",
        "|--------|-------|",
        f"| Total requirements | {len(all_reqs)} |",
        f"| Covered by tests | {len(covered_reqs)} |",
        f"| Waived | {len(waived_reqs)} |",
        f"| Uncovered | {len(uncovered_reqs)} |",
        "",
        "## Waivers",
        "",
        "- **NFR-001**: Availability/uptime — not testable in CI; monitored in production",
        "- **NFR-009**: Docker CPU limits — infrastructure concern, not application-level test",
        "",
        "## Coverage Detail",
        "",
        "| Requirement | Status |",
        "|-------------|--------|",
    ]

    for req in all_reqs:
        if req in covered:
            status = "✅ Covered"
        elif req in waivers:
            status = "⚠️ Waived"
        else:
            status = "❌ Uncovered"
        lines.append(f"| {req} | {status} |")

    output_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return len(covered_reqs), len(uncovered_reqs)


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Check spec compliance via test coverage"
    )
    parser.add_argument(
        "--output",
        default="SPEC_COMPLIANCE_REPORT.md",
        help="Output path for the compliance report",
    )
    args = parser.parse_args()

    output_path = Path(args.output)

    if not SPEC_FILE.exists():
        print(f"ERROR: Spec file not found: {SPEC_FILE}", file=sys.stderr)
        sys.exit(1)

    all_reqs = extract_requirements(SPEC_FILE)
    print(f"Found {len(all_reqs)} requirements in spec")

    covered = scan_covered(TESTS_DIR, E2E_TESTS_DIR)
    print(f"Found {len(covered)} requirement IDs referenced in tests")

    covered_count, uncovered_count = write_report(
        output_path, all_reqs, covered, WAIVERS
    )
    print(f"Report written to {output_path}")
    print(f"Covered: {covered_count}, Uncovered: {uncovered_count}")

    if uncovered_count > 0:
        print(
            f"FAIL: {uncovered_count} requirements uncovered and not waived",
            file=sys.stderr,
        )
        sys.exit(1)
    else:
        print("PASS: All requirements covered or waived")
        sys.exit(0)


if __name__ == "__main__":
    main()
