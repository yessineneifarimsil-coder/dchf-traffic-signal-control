"""Run the frozen evaluation stack on manifests with N != 2800 scheduled vehicles, in this process only.

The frozen code enforces the qualification count in two places reached during an evaluation:
  * adaptive_qmix.ledger.VehicleLedger.__init__ refuses len(records) != 2800;
  * adaptive_qmix.metrics.scheduled_demand_metrics divides J_primary's total by the constant 2800.0.
install() replaces the ledger constructor by an identical one without the count check, and wraps the
metrics function so that J_primary = total / N with N = the ledger's scheduled count (the manifest's
real total). For N = 2800 the wrapped function returns the frozen result unchanged. The wrapper is bound
into every module that imported the name. Nothing on disk is modified. Tested in tests/test_robustness.py.
"""
_INSTALLED = {}
METRIC_IMPORTERS = ("adaptive_qmix.metrics", "adaptive_qmix.evaluation", "adaptive_qmix.baselines.runner",
                    "adaptive_qmix_protected.evaluation")


def _ledger_init(self, records):
    from adaptive_qmix.ledger import LedgerError
    scheduled = {}
    for record in records:
        vehicle_id = str(record["vehicle_id"])
        if vehicle_id in scheduled:
            raise LedgerError("Duplicate scheduled vehicle ID: {}".format(vehicle_id))
        scheduled[vehicle_id] = int(record["depart"])
    if not scheduled:
        raise LedgerError("Empty ledger.")
    self.scheduled = scheduled
    self.inserted_at = {}
    self.completed_at = {}
    self.exceptional = {}
    self.teleport_started = set()
    self.teleport_ended = set()


def adapt_metrics(original):
    def scheduled_demand_metrics(ledger, tripinfo_rows, clearance_status):
        out = original(ledger, tripinfo_rows, clearance_status)
        n = len(ledger.scheduled)
        if n != 2800:
            if out["J_primary_valid"]:
                out["J_primary_mean_scheduled_waiting_burden_s"] = out["J_primary_total_scheduled_waiting_burden_vehicle_s"] / float(n)
            out["definition_note"] = ("J_primary is mean(waitingTime + departDelay) over all {} scheduled vehicles "
                                      "(robustness adapter: denominator = manifest total); it is not J_legacy.".format(n))
            out["J_denominator_scheduled_total"] = n
        return out
    scheduled_demand_metrics._adapted = True
    return scheduled_demand_metrics


def install():
    import importlib
    import adaptive_qmix.ledger as L
    import adaptive_qmix.metrics as M
    if _INSTALLED:
        return _INSTALLED
    _INSTALLED["ledger_init"] = L.VehicleLedger.__init__
    _INSTALLED["metrics"] = M.scheduled_demand_metrics
    L.VehicleLedger.__init__ = _ledger_init
    wrapped = adapt_metrics(M.scheduled_demand_metrics)
    for name in METRIC_IMPORTERS:
        mod = importlib.import_module(name)
        if getattr(mod, "scheduled_demand_metrics", None) is not None:
            mod.scheduled_demand_metrics = wrapped
    return _INSTALLED


def uninstall():
    import importlib
    import adaptive_qmix.ledger as L
    if not _INSTALLED:
        return
    L.VehicleLedger.__init__ = _INSTALLED["ledger_init"]
    for name in METRIC_IMPORTERS:
        mod = importlib.import_module(name)
        if hasattr(mod, "scheduled_demand_metrics"):
            mod.scheduled_demand_metrics = _INSTALLED["metrics"]
    _INSTALLED.clear()
