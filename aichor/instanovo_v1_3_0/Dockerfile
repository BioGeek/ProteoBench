FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PROTEOBENCH=0.0.0+aichor \
    UV_SYSTEM_PYTHON=1 \
    UV_PROJECT_ENVIRONMENT=/opt/venv \
    PATH="/opt/venv/bin:${PATH}"

WORKDIR /workspace/ProteoBench

RUN apt-get update \
    && apt-get install -yq --no-install-recommends \
        awscli \
        ca-certificates \
        curl \
        git \
        gzip \
    && rm -rf /var/lib/apt/lists/*

COPY . /workspace/ProteoBench

# DELIBERATELY UNSET. The v1.3 checkpoints cannot be loaded by any released instanovo: PyPI
# tops out at 1.2.2, and these are internal training artefacts (experiments 33768d55 and
# 8d0443f2) with a 133-residue vocabulary. The build therefore has to install instanovo from
# the internal source at a pinned commit, and there is no default that would be correct --
# pinning 1.2.2 here would build cleanly and then fail at checkpoint load, which is worse than
# failing now. Supply one of:
#
#   a wheel built from the internal repo and staged on the inputs bucket (preferred: no
#   credentials in the manifest, reproducible by sha)
#     --build-arg INSTANOVO_INSTALL_SPEC=https://<inputs-bucket>/wheels/instanovo-1.3.0.dev0+<sha>-py3-none-any.whl
#
#   or an authenticated git spec, if the build can carry a token as a secret
#     --build-arg INSTANOVO_INSTALL_SPEC="instanovo @ git+https://<token>@github.com/instadeepai/InstaNovo-internal.git@<sha>"
#
# See README.md in this directory for why this is the one thing "just update the checkpoints"
# does not cover.
ARG INSTANOVO_INSTALL_SPEC
ARG POLARS_INSTALL_SPEC=polars==1.41.2
# No upper bound on torch, unlike the v1.2.2 image. That pin existed because torch>=2.6's
# restricted unpickler refuses SETITEM on the defaultdict inside the 1.2.x checkpoints. The
# v1.3 checkpoints were written by torch 2.8.0+cu126 (see the inference logs of experiment
# 4cc23918), so pinning below 2.6 here would likely fail to load them at all.
ARG TORCH_INSTALL_SPEC="torch"

RUN test -n "${INSTANOVO_INSTALL_SPEC}" \
    || (echo "INSTANOVO_INSTALL_SPEC is unset; see the comment above -- no released instanovo can load the v1.3 checkpoints" >&2; exit 1)

RUN python -m pip install --no-cache-dir --upgrade pip uv \
    && uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python "${INSTANOVO_INSTALL_SPEC}" "${TORCH_INSTALL_SPEC}" \
    && uv pip install --python /opt/venv/bin/python -e ".[dev]" \
    && uv pip uninstall --python /opt/venv/bin/python polars-lts-cpu polars-runtime-32 polars \
    && uv pip install --python /opt/venv/bin/python "${POLARS_INSTALL_SPEC}" \
    && uv pip install --python /opt/venv/bin/python s3fs

# The sweep implementation is shared with the v1.2.2 run rather than copied: it takes the
# checkpoints as flags (`--instanovo-model` / `--instanovo-plus-model`), so a second copy would
# only be a second thing to keep in step.
WORKDIR /workspace/ProteoBench/aichor/instanovo_v1_2_2

CMD ["python", "run_sweep.py"]
