"""Export the CarePath pydantic model as JSON Schema to contracts/care_path.schema.json.

python -m app.care_paths.schema_export        (from backend/)
"""

from __future__ import annotations

import json
from typing import Any

from app.care_paths.loader import REPO_ROOT
from app.care_paths.models import CarePath

CONTRACT_FILE = REPO_ROOT / "contracts" / "care_path.schema.json"


def build_schema() -> dict[str, Any]:
    schema = CarePath.model_json_schema()
    return {
        "$schema": "https://json-schema.org/draft/2020-12/schema",
        "$id": "https://carecost.local/contracts/care_path.schema.json",
        **schema,
    }


def main() -> None:
    CONTRACT_FILE.parent.mkdir(parents=True, exist_ok=True)
    CONTRACT_FILE.write_text(json.dumps(build_schema(), indent=2, ensure_ascii=False) + "\n")
    print(f"wrote {CONTRACT_FILE}")


if __name__ == "__main__":
    main()
