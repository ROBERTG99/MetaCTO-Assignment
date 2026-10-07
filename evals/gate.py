"""CI eval gate: `make eval-gate`. Runs nothing paid. Checks the offline baseline results (written by
`make eval-offline`) against the floors in evals/gates.yaml, so a change that makes routing worse fails CI
for free. Floors sit about a point under the committed numbers, which absorbs float noise across machines."""

import json
import sys
from pathlib import Path
from typing import Any

import yaml

ROOT = Path(__file__).resolve().parents[1]
GATES = ROOT / "evals" / "gates.yaml"
RESULTS = ROOT / "evals" / "results"


def regressions(result: dict[str, Any], floors: dict[str, Any]) -> list[str]:
    out = []
    overall = result.get("overall", {})
    for metric, bound in floors.items():
        value = overall.get(metric)
        value = value.get("value") if isinstance(value, dict) else value
        if value is None:
            out.append(f"{metric} is missing from the result")
        elif "min" in bound and value < bound["min"]:
            out.append(f"{metric} {value:.4f} is below the floor {bound['min']:.4f}")
        elif "max" in bound and value > bound["max"]:
            out.append(f"{metric} {value:.4f} is above the ceiling {bound['max']:.4f}")
    return out


def main() -> int:
    gates = yaml.safe_load(GATES.read_text(encoding="utf-8"))
    failed = False
    for split, floors in gates.items():
        result = json.loads((RESULTS / f"{split}_baseline.json").read_text(encoding="utf-8"))
        problems = regressions(result, floors)
        print(f"{split}: {'OK' if not problems else '; '.join(problems)}")
        failed |= bool(problems)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
