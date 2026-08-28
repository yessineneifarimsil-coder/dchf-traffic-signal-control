from __future__ import absolute_import

import copy
import os
import sys


REPOSITORY_ROOT = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..")
)
SOURCE_ROOT = os.path.join(REPOSITORY_ROOT, "src")
if SOURCE_ROOT not in sys.path:
    sys.path.insert(0, SOURCE_ROOT)

from adaptive_qmix.config import load_config  # noqa: E402


CONFIG_PATH = os.path.join(
    REPOSITORY_ROOT, "config", "adaptive_qmix", "qualification_300m_medium.json"
)


def config_copy():
    return copy.deepcopy(load_config(CONFIG_PATH))


def ledger_records(depart=0):
    return [
        {"vehicle_id": "vehicle_{:04d}".format(index), "depart": int(depart)}
        for index in range(2800)
    ]

