"""The Judge's wire format, shared by the service and the pipeline: an explicit verdict, never
an echo of the input (J-3, SPEC §11 R-9)."""

import json
from typing import Literal

from pydantic import BaseModel


class Verdict(BaseModel):
    verdict: Literal["allow", "block"]
    reason: str


def parse_verdict(text: str) -> Verdict:
    """Strict: anything but a valid verdict raises, and the pipeline treats that as an error (J-4)."""
    return Verdict.model_validate(json.loads(text))
