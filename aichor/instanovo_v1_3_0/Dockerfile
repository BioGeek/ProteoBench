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

# A wheel built from InstaNovo-internal, vendored into this directory. No released instanovo
# can load the v1.3 checkpoints: PyPI tops out at 1.2.2, and these are internal training
# artefacts (experiments 33768d55 and 8d0443f2) with a 133-residue vocabulary.
#
#   built from: InstaNovo-internal test/v1-3-133res-inference @ 03a876d414f0 (clean tree)
#   sha256:     6747cb796f8a49ceae1772edfb8f34d87c8646350ea326a1f05662ba35f7e1df
#   archived:   s3://dtu-denovo-s-2e6da747d6d34f62-inputs/wheels/instanovo-1.3.0-03a876d414f0/
#   ships 45 config files, including configs/residues/extended.yaml (the 133-residue
#   vocabulary the checkpoints were trained on)
#
# Vendored rather than fetched from the bucket because this install runs at BUILD time, and the
# image build has no bucket credentials. The bucket copy is the canonical archive; the two are
# identical by the sha256 in wheels/SHA256SUMS. Override the arg to test another build.
ARG INSTANOVO_INSTALL_SPEC=aichor/instanovo_v1_3_0/wheels/instanovo-1.3.0-py3-none-any.whl
ARG POLARS_INSTALL_SPEC=polars==1.41.2
# No upper bound on torch, unlike the v1.2.2 image. That pin existed because torch>=2.6's
# restricted unpickler refuses SETITEM on the defaultdict inside the 1.2.x checkpoints. The
# v1.3 checkpoints were written by torch 2.8.0+cu126 (see the inference logs of experiment
# 4cc23918), so pinning below 2.6 here would likely fail to load them at all.
ARG TORCH_INSTALL_SPEC="torch"

# Verify the vendored wheel against its recorded checksum before installing it. A silently
# corrupted or stale wheel would otherwise surface much later as a checkpoint-loading error.
RUN if [ -f "${INSTANOVO_INSTALL_SPEC}" ]; then \
        cd "$(dirname "${INSTANOVO_INSTALL_SPEC}")" && sha256sum -c SHA256SUMS; \
    fi

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
