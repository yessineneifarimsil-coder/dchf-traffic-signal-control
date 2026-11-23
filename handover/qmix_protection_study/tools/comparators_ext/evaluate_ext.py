"""Comparator evaluation with the kinds of campaign A plus "actuated_g5" (campaign A-ext and campaign B).

tools/comparators/evaluate_comparator.py is not modified (its SHA-256 is fixed in campaign A's plan). This module
imports it and, in the importing process only, extends its two dispatch functions:
  * label(spec)            "actuated_g5:gap<g>_H<h>_V<v>_z<z>" for the new kind, unchanged otherwise;
  * executor_factory(spec) ActuatedGapOutG5Executor for the new kind, unchanged otherwise.
The evaluation sequence (frozen environment, logger, metrics, N adapter, identity stamp, completion marker) is
evaluate_comparator.evaluate itself. Spec of the new kind:
  {"kind": "actuated_g5", "params": {"gap_s": 2, "max_green_H_s": 45, "max_green_V_s": 15, "zone_m": 40}}
"""
from __future__ import absolute_import

import os
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
sys.path.insert(0, os.path.join(HERE, "..", "comparators"))

import evaluate_comparator as ec  # noqa: E402

KIND = "actuated_g5"
_ORIGINAL_LABEL = ec.label
_ORIGINAL_FACTORY = ec.executor_factory


def label(spec):
    if spec["kind"] == KIND:
        q = spec["params"]
        return "actuated_g5:gap{}_H{}_V{}_z{}".format(q["gap_s"], q["max_green_H_s"], q["max_green_V_s"],
                                                     int(q["zone_m"]))
    return _ORIGINAL_LABEL(spec)


def executor_factory(spec):
    if spec["kind"] == KIND:
        import controllers_g5 as G
        params = dict(spec["params"])
        return lambda tr, cf, e: G.ActuatedGapOutG5Executor(tr, cf, data_source=e.source, **params)
    return _ORIGINAL_FACTORY(spec)


ec.label = label
ec.executor_factory = executor_factory
spec_sha256 = ec.spec_sha256


def evaluate(spec, prefix, out_dir, counters=False, compact=True, traci_module=None):
    return ec.evaluate(spec, prefix, out_dir, counters=counters, compact=compact, traci_module=traci_module)
