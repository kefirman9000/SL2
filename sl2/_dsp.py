"""Shared constants for the analog-modelled synths (va, va_bass)."""
import numpy as np

SR = 44100


def mtof(m):
    return 440.0 * 2.0 ** ((np.asarray(m, dtype=float) - 69.0) / 12.0)
