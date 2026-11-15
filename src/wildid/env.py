"""Process environment that must be set before torch / huggingface_hub / ultralytics are imported.

Keep this module free of heavy imports.
"""

from __future__ import annotations

import os
import sys


def prepare_runtime_env(*, allow_model_download: bool) -> None:
    """Offline-first (plan D15): the classify path never downloads a model.

    HF_HUB_OFFLINE makes huggingface_hub serve every file from the local cache with zero
    network calls (no revision checks, no connection timeouts). Only `wildid prefetch` lifts it.
    """
    if allow_model_download:
        os.environ["HF_HUB_OFFLINE"] = "0"
    else:
        os.environ.setdefault("HF_HUB_OFFLINE", "1")
    os.environ.setdefault("HF_HUB_DISABLE_TELEMETRY", "1")
    os.environ.setdefault("HF_HUB_DISABLE_IMPLICIT_TOKEN", "0")
    # ultralytics (the --crop detector): no update checks, no analytics, no chatter. Its weights
    # are fetched by prefetch itself, so even prefetch keeps it offline.
    os.environ.setdefault("YOLO_OFFLINE", "true")
    os.environ.setdefault("YOLO_VERBOSE", "false")
    # pybioclip sets TORCH_FORCE_WEIGHTS_ONLY_LOAD=true unless it is already set, which forces
    # torch.load(weights_only=True) process-wide. The detector and SpeciesNet checkpoints are
    # pickled modules (checksummed, fetched by prefetch from their official sources), so keep
    # torch's default: the call site decides.
    os.environ.setdefault("TORCH_FORCE_WEIGHTS_ONLY_LOAD", "0")
    # Apple Silicon: an operator without a Metal (MPS) kernel runs on the CPU instead of
    # raising. torch reads this at import; it means nothing on CUDA or CPU-only machines.
    os.environ.setdefault("PYTORCH_ENABLE_MPS_FALLBACK", "1")
    _configure_torch_compile()


def _configure_torch_compile() -> None:
    """pybioclip wraps the model in torch.compile(). The first forward pass then compiles ViT-H
    (tens of seconds, needs a C compiler plus Triton, no Windows CUDA support), which breaks the
    "starts in seconds" requirement for a field tool. Eager mode is fast enough on a desktop GPU,
    so compilation stays off unless WILDID_TORCH_COMPILE=1."""
    if os.environ.get("WILDID_TORCH_COMPILE", "0") != "1":
        os.environ.setdefault("TORCH_COMPILE_DISABLE", "1")


def force_utf8_stdio() -> None:
    """Common names carry diacritics; Windows consoles default to a legacy code page."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
