"""Dependency-hygiene guard: the backend must ship the CPU-only torch build.

torch is a transitive dependency of ``unstructured[pdf]`` (via
``unstructured-inference`` / ``timm``) and is NEVER executed at runtime — the PDF
parser uses ``strategy="fast"`` (pdfminer.six text path), not the ML ``hi_res``
path. The Dockerfile therefore installs ``torch==X+cpu`` from PyTorch's CPU index
so the image doesn't carry the ~1.5-2 GB NVIDIA CUDA stack (#264).

These tests fail loudly if a future dependency bump silently re-pulls the GPU
build, so the image bloat / CVE-surface can't creep back unnoticed. They read
installed *distribution metadata* (not ``import torch``) so they're cheap and
don't depend on torch being importable.

NB: they assert the state of the INSTALLED environment, so they only pass inside
the built image (or a venv provisioned the same way) — the CPU-only build.
"""
from __future__ import annotations

import importlib.metadata as md

import pytest


def _installed_names() -> set[str]:
    return {
        (dist.metadata["Name"] or "").lower()
        for dist in md.distributions()
    }


@pytest.mark.skipif(
    "torch" not in _installed_names(),
    reason="torch not installed (light/dev env without the unstructured[pdf] stack)",
)
def test_torch_is_cpu_only_build() -> None:
    version = md.version("torch")
    assert version.endswith("+cpu"), (
        f"torch must be the CPU-only build (…+cpu), got {version!r}. A dependency "
        "bump likely re-pulled the CUDA build — re-pin the CPU wheel in "
        "backend/Dockerfile (#264)."
    )


def test_no_nvidia_cuda_packages_installed() -> None:
    nvidia = sorted(
        name for name in _installed_names() if name.startswith("nvidia-")
    )
    assert nvidia == [], (
        f"Unexpected NVIDIA/CUDA packages installed: {nvidia}. The backend runs "
        "CPU-only; these come with the CUDA torch build and bloat the image. "
        "Ensure torch is installed from the CPU index (backend/Dockerfile, #264)."
    )
