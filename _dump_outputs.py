import json
import os
import sys
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app.adapters.mock_adapter import MockAdapter
from app.service.cutline_service import CutlineService
from app.service.mix_trace_service import MixTraceService
from app.schemas.request_schema import MixTraceRequest

ROOT = Path(os.path.dirname(os.path.abspath(__file__)))

cutline_inputs = [
    "examples/cutline_sample_input.json",
    "examples/cutline_complex_input.json",
    "examples/cutline_overflow_input.json",
    "examples/cutline_return_input.json",
    "examples/cutline_silk_screen_input.json",
]

for rel in cutline_inputs:
    print("=" * 70)
    print("CUTLINE INPUT:", rel)
    print("=" * 70)
    try:
        snap = MockAdapter().load(ROOT / rel)
        resp = CutlineService().evaluate(snap)
        print(resp.model_dump_json(indent=2))
    except Exception as exc:  # noqa
        print("ERROR:", type(exc).__name__, exc)
    print()

print("=" * 70)
print("MIX TRACE INPUT: examples/cutline_mix_trace_input.json")
print("=" * 70)
try:
    payload = json.loads((ROOT / "examples/cutline_mix_trace_input.json").read_text(encoding="utf-8"))
    req = MixTraceRequest.model_validate(payload)
    resp = MixTraceService().trace(req)
    print(resp.model_dump_json(indent=2))
except Exception as exc:  # noqa
    print("ERROR:", type(exc).__name__, exc)
