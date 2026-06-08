from __future__ import annotations

import dataclasses
import math
from datetime import date, datetime
from decimal import Decimal
from enum import Enum
from pathlib import Path
from typing import Any

try:  # NumPy is available in the VAD service, but keep this helper import-safe.
    import numpy as np  # type: ignore
except Exception:  # pragma: no cover - defensive for minimal environments
    np = None  # type: ignore


def sanitize_json(value: Any) -> Any:
    """Return a PostgreSQL-JSONB-safe representation of *value*.

    PostgreSQL JSON/JSONB rejects non-standard JSON tokens such as NaN,
    Infinity and -Infinity. Gate feature/metadata dictionaries can contain
    NumPy scalars/arrays and values produced by numerical code, so sanitize
    recursively immediately before DB serialization.
    """
    if value is None or isinstance(value, (str, bool)):
        return value

    # Keep normal Python ints, but avoid bool being treated as int above.
    if isinstance(value, int):
        return value

    if isinstance(value, float):
        return value if math.isfinite(value) else None

    if isinstance(value, Decimal):
        try:
            as_float = float(value)
        except Exception:
            return str(value)
        return as_float if math.isfinite(as_float) else None

    if np is not None:
        if isinstance(value, np.generic):
            return sanitize_json(value.item())
        if isinstance(value, np.ndarray):
            return sanitize_json(value.tolist())

    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            # JSON object keys must be strings. Convert unusual keys safely.
            if isinstance(key, str):
                safe_key = key
            elif isinstance(key, (int, float, bool)) or key is None:
                safe_key = str(sanitize_json(key))
            else:
                safe_key = str(key)
            out[safe_key] = sanitize_json(item)
        return out

    if isinstance(value, (list, tuple, set, frozenset)):
        return [sanitize_json(item) for item in value]

    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return sanitize_json(dataclasses.asdict(value))

    if isinstance(value, Enum):
        return sanitize_json(value.value)

    if isinstance(value, (datetime, date)):
        return value.isoformat()

    if isinstance(value, Path):
        return str(value)

    if hasattr(value, "tolist"):
        try:
            return sanitize_json(value.tolist())
        except Exception:
            pass

    if hasattr(value, "item"):
        try:
            return sanitize_json(value.item())
        except Exception:
            pass

    return str(value)
