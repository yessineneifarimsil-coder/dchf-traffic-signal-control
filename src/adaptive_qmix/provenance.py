"""Runtime provenance captured automatically for every adaptive run."""

from __future__ import absolute_import

import hashlib
import json
import os
import platform
import subprocess
import sys

import numpy as np

from .config import config_sha256
from .rng import namespace_manifest


def sha256_file(path):
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _command(args, cwd=None):
    output = subprocess.check_output(args, cwd=cwd, stderr=subprocess.STDOUT)
    return output.decode("utf-8", errors="replace").strip()


def _git_value(repository_root, args):
    try:
        return _command(["git"] + list(args), cwd=repository_root)
    except (OSError, subprocess.CalledProcessError):
        return None


def _sumo_version():
    try:
        first_line = _command(["sumo", "--version"]).splitlines()[0]
        return first_line.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def runtime_versions(device):
    import torch

    cuda_device = None
    if torch.cuda.is_available():
        cuda_device = torch.cuda.get_device_name(torch.cuda.current_device())
    return {
        "python": platform.python_version(),
        "python_full": sys.version,
        "numpy": np.__version__,
        "pytorch": torch.__version__,
        "device": str(device),
        "device_name": cuda_device or platform.processor() or "CPU",
        "cuda": torch.version.cuda,
        "cudnn": (
            torch.backends.cudnn.version()
            if hasattr(torch.backends, "cudnn") else None
        ),
        "torch_deterministic_algorithms": bool(
            torch.are_deterministic_algorithms_enabled()
        ),
        "cudnn_deterministic": (
            bool(torch.backends.cudnn.deterministic)
            if hasattr(torch.backends, "cudnn") else None
        ),
        "cudnn_benchmark": (
            bool(torch.backends.cudnn.benchmark)
            if hasattr(torch.backends, "cudnn") else None
        ),
        "sumo": _sumo_version(),
    }


def build_run_manifest(
    repository_root,
    config,
    route_manifest_path,
    checkpoint_path,
    method,
    training_seed,
    traffic_seed,
    device,
    run_kind,
):
    clean_config = {
        key: value for key, value in config.items() if not key.startswith("_")
    }
    network_path = os.path.join(repository_root, config["network"]["path"])
    manifest = {
        "schema_version": "1.3a",
        "run_kind": str(run_kind),
        "method": str(method),
        "git_commit": _git_value(repository_root, ["rev-parse", "HEAD"]),
        "git_branch": _git_value(
            repository_root, ["branch", "--show-current"]
        ),
        "git_describe": _git_value(
            repository_root, ["describe", "--tags", "--always", "--dirty"]
        ),
        "git_status_porcelain": _git_value(
            repository_root, ["status", "--porcelain"]
        ),
        "config_sha256": config_sha256(clean_config),
        "network_sha256": sha256_file(network_path),
        "network_git_blob": _git_value(
            repository_root, ["hash-object", "--", config["network"]["path"]]
        ),
        "route_manifest_sha256": sha256_file(route_manifest_path),
        "checkpoint_sha256": (
            sha256_file(checkpoint_path) if checkpoint_path else None
        ),
        "training_seed": None if training_seed is None else int(training_seed),
        "traffic_seed": int(traffic_seed),
        "rng_namespaces": (
            None if training_seed is None else namespace_manifest(training_seed)
        ),
        "runtime": runtime_versions(device),
        "reproducibility_scope": (
            "Bitwise reproducibility is claimed only for the same software stack, "
            "device class, and deterministic-algorithm settings."
        ),
    }
    if manifest["network_sha256"] != config["network"]["sha256"]:
        raise RuntimeError("Runtime network SHA-256 differs from frozen configuration.")
    if manifest["network_git_blob"] != config["network"]["git_blob"]:
        raise RuntimeError("Runtime network Git blob differs from frozen configuration.")
    return manifest


def write_run_manifest(path, manifest):
    directory = os.path.dirname(os.path.abspath(path))
    if not os.path.isdir(directory):
        os.makedirs(directory)
    with open(path, "w") as handle:
        json.dump(manifest, handle, indent=2, sort_keys=True)

