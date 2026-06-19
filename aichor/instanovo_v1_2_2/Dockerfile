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

ARG INSTANOVO_INSTALL_SPEC=instanovo==1.2.2
ARG POLARS_INSTALL_SPEC=polars==1.41.2

RUN python -m pip install --no-cache-dir --upgrade pip uv \
    && uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python "${INSTANOVO_INSTALL_SPEC}" \
    && uv pip install --python /opt/venv/bin/python ".[dev]" \
    && uv pip uninstall --python /opt/venv/bin/python polars-lts-cpu polars-runtime-32 polars \
    && uv pip install --python /opt/venv/bin/python "${POLARS_INSTALL_SPEC}" \
    && uv pip install --python /opt/venv/bin/python s3fs

WORKDIR /workspace/ProteoBench/aichor/instanovo_v1_2_2

CMD ["python", "run_sweep.py"]
