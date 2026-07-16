"""Run the current cutline algorithm service with the bundled request sample."""

import json
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from app.schemas.request_schema import CutlineAlgorithmRequest
from app.service.cutline_service import CutlineService


REQUEST_PATH = ROOT_DIR / "examples" / "backend_request_sample.json"


def main() -> None:
    with REQUEST_PATH.open(encoding="utf-8") as file:
        request = CutlineAlgorithmRequest.model_validate(json.load(file))

    response = CutlineService().evaluate_algorithm(request)
    print(response.model_dump_json(indent=2))


if __name__ == "__main__":
    main()
