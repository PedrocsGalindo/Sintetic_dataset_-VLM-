"""Random seed helpers."""

from __future__ import annotations

import os
import random
from dataclasses import dataclass

try:
    import numpy as np
except ImportError:  # pragma: no cover - dependency is optional during bootstrap
    np = None


@dataclass(frozen=True)
class SeedState:
    """Report which seed was applied to the runtime."""

    seed: int
    numpy_available: bool


def set_global_seed(seed: int) -> SeedState:
    """Set the random seed for the supported libraries."""

    os.environ["PYTHONHASHSEED"] = str(seed)
    random.seed(seed)
    if np is not None:
        np.random.seed(seed)
    return SeedState(seed=seed, numpy_available=np is not None)
