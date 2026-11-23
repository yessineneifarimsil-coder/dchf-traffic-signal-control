"""Actuated gap-out controller with a 5 s minimum green (campaign A-ext). New file: tools/comparators/controllers.py,
whose SHA-256 is fixed in campaign A's plan, is not modified, and its 7 s variant keeps refusing anything below 7 s.

ActuatedGapOutG5Executor has exactly the behaviour of ActuatedGapOutExecutor (detection zone, gap timer,
conflicting call, gap-out / max-out, rest in green, 3 s yellow) with minimum_green_s = 5 instead of 7. It is
built by letting the parent validate a 7 s instance and then setting the 5 s minimum, so no line of the parent
is changed; the parent's per-second logic reads self.minimum_green_s.
"""
from __future__ import absolute_import

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "comparators"))

from controllers import ActuatedGapOutExecutor  # noqa: E402

MIN_GREEN_G5_S = 5
TIMING_ACTUATED_G5 = "actuated_gap_out_min_green_5"


class ActuatedGapOutG5Executor(ActuatedGapOutExecutor):
    timing_authority = TIMING_ACTUATED_G5

    def __init__(self, traci_module, config, data_source=None, gap_s=2, max_green_H_s=45, max_green_V_s=15,
                 zone_m=40.0, minimum_green_s=MIN_GREEN_G5_S, yellow_s=3):
        if int(minimum_green_s) != MIN_GREEN_G5_S:
            raise ValueError("The g5 actuated variant has a 5 s minimum green exactly.")
        if min(int(max_green_H_s), int(max_green_V_s)) < MIN_GREEN_G5_S or int(gap_s) < 1:
            raise ValueError("Maximum greens must be >= 5 s and the gap >= 1 s.")
        # The parent validates against 7 s: give it valid maxima, then set the real values.
        super(ActuatedGapOutG5Executor, self).__init__(
            traci_module, config, data_source=data_source, gap_s=gap_s,
            max_green_H_s=max(int(max_green_H_s), 7), max_green_V_s=max(int(max_green_V_s), 7), zone_m=zone_m,
            minimum_green_s=7, yellow_s=yellow_s)
        self.max_green = {"H": int(max_green_H_s), "V": int(max_green_V_s)}
        self.minimum_green_s = MIN_GREEN_G5_S
