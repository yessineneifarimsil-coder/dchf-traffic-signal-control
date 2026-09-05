"""Adaptive signal-timing QMIX qualification implementation.

This package is intentionally isolated from the legacy DCHF controllers.
The primary control semantics is frozen at 5 s decisions, EXTEND = 5 s and
SWITCH = 3 s yellow + 2 s new green, with no imposed minimum or maximum green.
Scientific runs still require an explicit unlock, taken only after the
pre-final audit.
"""

__version__ = "0.1.0"

