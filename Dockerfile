# Single image for every stage of astril-nf. CPU-only tasks (organize/convert/quantify) and
# GPU-labeled tasks (preprocess/segment) both run this image; Nextflow/Cirro selects the
# instance type and GPU visibility per process via conf/gpu.config or Cirro's
# process-compute.config -- the image itself does not need to differ per stage.
#
# Both the GBM model checkpoints (~1.8GB, astril-download-models) and HD-BET's own pretrained
# parameters (~0.5GB, from Zenodo) are downloaded here at BUILD time, not at pipeline runtime,
# so tasks never depend on external network egress from inside the Batch execution environment.
FROM nvidia/cuda:12.4.1-cudnn-runtime-ubuntu22.04

ENV DEBIAN_FRONTEND=noninteractive \
    PIP_NO_CACHE_DIR=1 \
    PYTHONUNBUFFERED=1 \
    HOME=/root

# Ubuntu 22.04's own apt archive ships python3.11 as build 3.11.0~rc1 (it predates jammy's
# default 3.10 and was never updated in-place) -- missing stdlib additions finalized between rc1
# and the real 3.11.0 release (e.g. sys.get_int_max_str_digits), which crashes modern PyTorch's
# _dynamo polyfills at import time (AttributeError, surfaced via hd-bet -> nnunetv2 -> torch).
# The deadsnakes PPA maintains genuinely current, patched Python builds for Ubuntu and is the
# standard fix for this exact class of problem.
RUN apt-get update && apt-get install -y --no-install-recommends \
        software-properties-common \
    && add-apt-repository -y ppa:deadsnakes/ppa \
    && apt-get update && apt-get install -y --no-install-recommends \
        python3.11 python3.11-venv python3.11-distutils \
        git curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN curl -sS https://bootstrap.pypa.io/get-pip.py | python3.11 \
    && update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1 \
    && update-alternatives --install /usr/bin/python python /usr/bin/python3.11 1

# astril is not (yet) on PyPI; pip installs directly from the git ref, matching the pattern in
# the (now superseded) prototype build at E:\Automated_MRI_Segmentation\astril_docker. A fresh
# git clone is used internally by pip's VCS installer, so a locally dirty checkout (e.g. the
# stale build/lib/astril/* duplicate modules) is never picked up.
ARG ASTRIL_GIT_URL=https://github.com/Alexander-Ling/astril
# Pinned to an exact astril commit so a given image tag always contains the same code; bump
# deliberately (and re-tag the image) when picking up astril changes.
ARG ASTRIL_GIT_REF=2af29645e4ed3483bd36b23401093daf05f1b3a9
# Cache buster: bump this (or pass --build-arg) to force re-pulling ASTRIL_GIT_REF and
# re-running the model downloads below, since Docker would otherwise cache this layer forever.
ARG ASTRIL_CACHEBUST=0
# PyTorch is installed FIRST, pinned to a CUDA 12.6 build: astril only requires `torch>=2.0`, so
# left alone pip pulls PyPI's newest default wheel, which is built for CUDA 13 and needs an
# NVIDIA driver >= 580 on the host. Cirro/AWS Batch GPU instances run whatever driver their AMI
# ships, which we don't control; a cu126 build runs on drivers back to the 525 series as well as
# current ones. Same torch version as the image validated locally (2.14.0), just a different CUDA
# build. pip then treats astril's `torch>=2.0` as already satisfied and leaves it alone.
ARG TORCH_VERSION=2.14.0
ARG TORCHVISION_VERSION=0.29.0
ARG TORCH_CUDA=cu126
RUN echo "astril code cachebust=${ASTRIL_CACHEBUST}" \
    && python3 -m pip install --upgrade pip \
    && python3 -m pip install --index-url "https://download.pytorch.org/whl/${TORCH_CUDA}" \
        "torch==${TORCH_VERSION}" "torchvision==${TORCHVISION_VERSION}" \
    && python3 -m pip install "astril[preprocessing] @ git+${ASTRIL_GIT_URL}@${ASTRIL_GIT_REF}" \
    && python3 -c "import torch; v = torch.version.cuda; assert v.startswith('12.'), f'torch CUDA {v} (expected 12.x): a dependency upgraded torch'"
# dcm2niix is already a declared astril dependency (pyproject.toml) and is installed above;
# astril's ensure_dcm2niix_accessible() resolves it on PATH.

# Bake in the GBM model checkpoints so no run-time download is needed.
#
# astril.paths.preferred_models_dir() (used by locate_models_dir() at inference time) prefers
# the package-local `models/` directory ONLY if the CURRENT user can write to it
# (os.access(..., os.W_OK)) -- otherwise it silently falls back to a per-user cache dir and
# finds nothing baked in here. nextflow.config deliberately does not run containers as a
# remapped host UID (see its `docker`/`gpu` profiles) to keep this resolution stable, but the
# models dir is also made world-writable as defense in depth against a runtime environment
# (e.g. Cirro/AWS Batch) invoking the container as a different user regardless.
RUN echo "astril models cachebust=${ASTRIL_CACHEBUST}" \
    && astril-download-models --family GBM_seg_v2 \
    && MODELS_DIR=$(python3 -c "from astril.paths import package_models_dir; print(package_models_dir())") \
    && chmod -R a+rwX "${MODELS_DIR}"

# Bake in HD-BET's own pretrained parameters (a third-party dependency, not astril's own code).
# HD_BET.paths.folder_with_parameter_files resolves to ~/hd-bet_params/release_2.0.0 (HOME-
# relative, same caching caveat as astril's own model dir above -- covered by ENV HOME=/root
# plus not remapping the runtime UID). Verified against the installed HD_BET package source
# (HD_BET/checkpoint_download.py): maybe_download_parameters() is the actual fetch trigger,
# downloading from Zenodo.
RUN python3 -c "from HD_BET.checkpoint_download import maybe_download_parameters; maybe_download_parameters()" \
    && chmod -R a+rwX "${HOME}/hd-bet_params"

# Licensing/attribution for the third-party code and pretrained weights baked into this image
# (HD-BET weights and GBM_seg_v2 are both non-commercial) -- see THIRD_PARTY_NOTICES.md.
COPY LICENSE THIRD_PARTY_NOTICES.md /licenses/astril-nf/

# Version metadata. ASTRIL_VERSION must be bumped together with ASTRIL_GIT_REF; the build fails
# if it doesn't match the installed package, so the label can't drift from the code. Declared
# down here (not with ASTRIL_GIT_REF) so changing them doesn't invalidate the heavy layers above.
ARG ASTRIL_NF_VERSION=0.2.0
ARG ASTRIL_VERSION=0.7.31
RUN python3 -c "from importlib.metadata import version; v = version('astril'); assert v == '${ASTRIL_VERSION}', f'installed astril {v} != ASTRIL_VERSION ${ASTRIL_VERSION}'"

LABEL org.opencontainers.image.source="https://github.com/Alexander-Ling/astril-nf" \
      org.opencontainers.image.description="astril-nf: DICOM ingestion, MRI preprocessing, and GBM segmentation (research use only, non-commercial)" \
      org.opencontainers.image.version="${ASTRIL_NF_VERSION}" \
      io.github.alexander-ling.astril.version="${ASTRIL_VERSION}" \
      io.github.alexander-ling.astril.git-ref="${ASTRIL_GIT_REF}"

WORKDIR /work
