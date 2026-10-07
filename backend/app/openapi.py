"""Write the OpenAPI schema to backend/openapi.json without starting a server. Run: `make openapi`."""

import json
from pathlib import Path

from app.main import create_app

OUT = Path(__file__).resolve().parents[1] / "openapi.json"


def main() -> None:
    schema = create_app().openapi()
    OUT.write_text(json.dumps(schema, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(f"Wrote {OUT.name} ({len(schema['paths'])} paths)")


if __name__ == "__main__":
    main()
