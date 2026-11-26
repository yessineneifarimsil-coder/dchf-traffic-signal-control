"""training_facts.json: training and checkpoint-selection facts, each with its source file and line, read-only.

    python tools/export_b/training_facts.py --frozen <QMIX_Traffic_Coordination> [--protected <QMIX_PROTECTED>]
        [--rob <robustness root>] --out <EXPORT>

Every value is read from a file; a value found nowhere is written "non disponible". The frozen training code is the
repository QMIX_Traffic_Coordination (commit 8c14f32 for B). Whether the 30 checkpoints of B were produced by this
code is NOT established here: the checkpoints come from the robustness plan (<ROB>/plan.json, "models"), whose
"source" fields are reported as they are.
"""
from __future__ import absolute_import, division, print_function

import argparse
import json
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

import common as C  # noqa: E402

CONFIG = os.path.join("config", "adaptive_qmix", "qualification_300m_medium.json")
SRC = os.path.join("src", "adaptive_qmix")
NA = "non disponible"


class Facts(object):
    def __init__(self, root, label):
        self.root, self.label = root, label

    def cite(self, rel, pattern, many=False):
        path = os.path.join(self.root, rel)
        if not os.path.isfile(path):
            return {"value": NA, "source": "{}/{} absent".format(self.label, rel.replace(os.sep, "/"))}
        hits = C.find_lines(path, pattern)
        if not hits:
            return {"value": NA, "source": "{}/{}: pattern {!r} not found".format(self.label, rel.replace(os.sep, "/"), pattern)}
        rows = [{"file": "{}/{}".format(self.label, rel.replace(os.sep, "/")), "line": n, "text": t.strip()} for n, t in hits]
        return rows if many else rows[0]

    def config_value(self, section, key):
        path = os.path.join(self.root, CONFIG)
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        value = data.get(section, {}).get(key, NA)
        where = self.cite(CONFIG, r'^\s*"{}"\s*:'.format(re.escape(key)))
        return {"value": value, "source": where}


def scan_dirs(dirs, patterns, label_of):
    """[(file, line, text)] of the .py files of dirs matching any pattern (callers of the checkpoint selection)."""
    out = []
    for d in dirs:
        for base, sub, names in os.walk(d):
            sub[:] = sorted(x for x in sub if x not in ("__pycache__", ".git"))
            for n in sorted(names):
                if n.endswith(".py"):
                    p = os.path.join(base, n)
                    for pat in patterns:
                        for line, text in C.find_lines(p, pat):
                            out.append({"file": label_of(p), "line": line, "text": text.strip()})
    return out


def collect(frozen, protected=None, rob=None):
    F = Facts(frozen, "<frozen>")
    t = lambda k: F.config_value("training", k)  # noqa: E731
    facts = {
        "optimizer": {
            "class": F.cite(os.path.join(SRC, "learner.py"), r"torch\.optim\.Adam\("),
            "learning_rate": t("learning_rate"),
            "other_parameters": {"value": "not set in the code: torch.optim.Adam defaults of the installed PyTorch "
                                          "(betas, eps, weight_decay, amsgrad)",
                                 "source": F.cite(os.path.join(SRC, "learner.py"), r"parameter_groups, lr=")},
            "loss": F.cite(os.path.join(SRC, "learner.py"), r"SmoothL1Loss"),
            "huber_beta": t("huber_beta"),
            "gradient_clipping_l2": t("gradient_max_l2_norm"),
            "gradient_clipping_call": F.cite(os.path.join(SRC, "learner.py"), r"clip_grad_norm_"),
            "double_dqn_target": F.cite(os.path.join(SRC, "learner.py"), r"def _double_dqn_target_local_q"),
            "gamma_per_5s": t("gamma_per_5s"),
            "idqn_loss": F.cite(os.path.join(SRC, "learner.py"), r'if self\.method == "idqn"'),
        },
        "update_schedule": {
            "interaction_budget_transitions": t("interaction_budget"),
            "replay_warmup_transitions": t("replay_warmup"),
            "learner_events_expected": t("learner_events"),
            "one_update_per_transition_after_warmup": F.cite(os.path.join(SRC, "training.py"), r"if transition_index > warmup"),
            "batch_size": t("batch_size"),
            "replay_capacity": t("replay_capacity"),
            "replay_sampling": F.cite(os.path.join(SRC, "replay.py"), r"generator\.choice\("),
            "target_hard_update_every_learner_events": t("target_hard_update_events"),
            "target_update_call": F.cite(os.path.join(SRC, "learner.py"), r"learner_events % self\.target_update_frequency"),
            "epsilon_start": t("epsilon_start"), "epsilon_end": t("epsilon_end"),
            "epsilon_decay_transitions": t("epsilon_decay_transitions"),
            "epsilon_schedule": F.cite(os.path.join(SRC, "learner.py"), r"def epsilon_at_transition"),
            "checkpoint_transitions": t("checkpoint_transitions"),
            "training_seeds": t("training_seeds"),
            "decision_interval_s": F.config_value("executor", "control_interval_s"),
        },
        "checkpoint_selection": {
            "rule": F.cite(os.path.join(SRC, "protocol", "statistics.py"), r'def select_checkpoint'),
            "order": F.cite(os.path.join(SRC, "protocol", "statistics.py"), r'float\(record\["mean_J_primary_s"\]\)'),
            "validation_family": F.cite(os.path.join(SRC, "protocol", "statistics.py"), r'^LEARNER_VALIDATION_FAMILY = '),
            "validation_traffic_seeds": F.cite(os.path.join(SRC, "protocol", "statistics.py"), r'^LEARNER_VALIDATION_SEEDS = '),
            "all_preregistered_checkpoints_required": F.cite(os.path.join(SRC, "protocol", "statistics.py"),
                                                             r"Checkpoint selection requires all"),
            "checkpoints": F.cite(os.path.join(SRC, "protocol", "statistics.py"), r'^CHECKPOINT_TRANSITIONS = \('),
            "episodes_per_validation_seed": {"value": NA, "source": "not stated in the frozen repository: the caller of "
                                             "select_checkpoint is not in it (see callers_found_in_protected)"},
            "validation_rng_namespace": F.cite(os.path.join(SRC, "rng.py"), r'"checkpoint_validation"'),
        },
        "eligibility_gates": {
            "training_success_definition": F.cite(os.path.join(SRC, "protocol", "statistics.py"), r'^TRAINING_SUCCESS_DEFINITION'),
            "training_seed_succeeded": F.cite(os.path.join(SRC, "protocol", "statistics.py"), r"def training_seed_succeeded"),
            "conditions": F.cite(os.path.join(SRC, "protocol", "statistics.py"),
                                 r"TRAINING_BUDGET_TRANSITIONS\b|completed_under_contract|checkpoints_present|selected_on_family|selected_on_seeds",
                                 many=True),
            "run_validity_gates": F.cite(os.path.join(SRC, "protocol", "validity.py"),
                                         r'^\s+"(all_scheduled|cleared|no_unexpected|no_unresolved|complete_one|scientific_analysis|finite_primary)',
                                         many=True),
        },
        "training_traffic": {
            "per_episode_manifest": F.cite(os.path.join(SRC, "training.py"), r"def _manifest_for_episode"),
            "manifest_family": F.cite(os.path.join(SRC, "training.py"), r'manifest_family = "training" if'),
            "manifest_entropy": F.cite(os.path.join(SRC, "traffic.py"), r"def _stream_generator", ),
            "sumo_seed_per_episode": F.cite(os.path.join(SRC, "traffic.py"), r"def derive_sumo_seed"),
        },
        "shared_by_two_methods_with_the_same_seed_number": {
            "namespaces": F.cite(os.path.join(SRC, "rng.py"), r'^\s+"(local_init_J1|local_init_J2|qmix_mixer_init|epsilon_J1|epsilon_J2|replay_sampling|traffic_manifest|sumo_episode|checkpoint_validation)":',
                                 many=True),
            "seed_sequence_has_no_method": F.cite(os.path.join(SRC, "rng.py"), r"def seed_sequence"),
            "local_networks": F.cite(os.path.join(SRC, "models.py"), r'for agent_index, namespace in enumerate\(\("local_init_J1"'),
            "qmix_mixer_only": F.cite(os.path.join(SRC, "models.py"), r'uint32_seed\(training_seed, "qmix_mixer_init"\)'),
            "epsilon_streams": F.cite(os.path.join(SRC, "training.py"), r"IndependentEpsilonStreams\(training_seed"),
            "epsilon_draws_always_consumed": F.cite(os.path.join(SRC, "rng.py"), r"keeping RNG consumption identical"),
            "replay_rng": F.cite(os.path.join(SRC, "training.py"), r'numpy_rng\(training_seed, "replay_sampling"\)'),
            "python_torch_seed": F.cite(os.path.join(SRC, "rng.py"), r'python_seed = uint32_seed\(training_seed, "local_init_J1", index=999\)'),
            "reading": (
                "From these lines: two policies of different methods with the same seed number start from the SAME "
                "initial local networks J1 and J2 (same architecture, same seed); QMIX alone adds a mixer with its own "
                "seed; they draw the SAME exploration random numbers (threshold and candidate action, two per agent "
                "and decision, drawn even when the greedy action is taken) and the SAME replay sampling stream (the "
                "indices depend only on the buffer size, equal at equal transition counts); episode k uses the SAME "
                "traffic manifest and SUMO seed. They do NOT share actions, trajectories or replay contents: greedy "
                "actions differ between methods, and episodes end at clearance, so the same transition index can fall "
                "in different episodes. Valid only if the checkpoints were trained by this code (not verified here)."),
        },
    }
    callers = []
    if protected and os.path.isdir(protected):
        callers = scan_dirs([os.path.join(protected, "src")],
                            [r"select_checkpoint\(", r"checkpoint_validation", r"LEARNER_VALIDATION_SEEDS",
                             r"torch\.optim\.", r"learning_rate"],
                            lambda p: "<PROTECTED>/" + os.path.relpath(p, protected).replace(os.sep, "/"))
    facts["checkpoint_selection"]["callers_found_in_protected"] = callers or NA
    provenance = NA
    logs = []
    if rob and os.path.isfile(os.path.join(rob, "plan.json")):
        with open(os.path.join(rob, "plan.json"), encoding="utf-8") as f:
            models = json.load(f).get("models", [])
        provenance = [{"tag": m.get("tag"), "method": m.get("method"), "source": m.get("source", NA),
                       "sha256": m.get("sha256")} for m in models]
        for m in models:
            src = m.get("source")
            if src and os.path.exists(os.path.dirname(src)):
                for name in sorted(os.listdir(os.path.dirname(src))):
                    if re.search(r"valid", name, re.I):
                        logs.append(os.path.join(os.path.dirname(src), name))
    facts["checkpoints_of_B"] = {"from_robustness_plan": provenance}
    facts["validation_logs_per_checkpoint"] = {
        "files_named_like_validation_next_to_the_checkpoint_sources": sorted(set(logs)) or NA,
        "note": "a curve of validation J per checkpoint needs the 14 validation records of each training seed; "
                "if no such file is listed here, it is not available from these sources"}
    return facts


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--frozen", required=True)
    ap.add_argument("--protected")
    ap.add_argument("--rob")
    ap.add_argument("--out", required=True)
    a = ap.parse_args(argv)
    facts = collect(a.frozen, a.protected, a.rob)
    scrub = C.Scrubber(export=a.out, extra=tuple((p, t) for p, t in ((a.frozen, "<frozen>"), (a.protected, "<PROTECTED>"),
                                                                    (a.rob, "<ROB>")) if p))
    C.write_json_once(os.path.join(a.out, "training_facts.json"), facts, scrub)
    na = json.dumps(facts).count(NA)
    print("training_facts.json written ({} value(s) 'non disponible')".format(na))
    return 0


if __name__ == "__main__":
    sys.exit(main())
