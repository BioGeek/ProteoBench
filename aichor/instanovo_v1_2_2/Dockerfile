FROM pytorch/pytorch:2.7.1-cuda12.8-cudnn9-runtime

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
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

RUN python -m pip install --no-cache-dir --upgrade pip uv \
    && uv venv /opt/venv \
    && uv pip install --python /opt/venv/bin/python "${INSTANOVO_INSTALL_SPEC}" \
    && uv pip install --python /opt/venv/bin/python ".[dev]" \
    && uv pip install --python /opt/venv/bin/python boto3

WORKDIR /workspace/ProteoBench/aichor/instanovo_v1_2_2

CMD ["python", "run_sweep.py"]
