# CPU-only image for scoring completed internal runs with ProteoBench's metrics.
#
# Deliberately not built on the sweep's image (aichor/instanovo_v1_2_2/Dockerfile): that one
# carries CUDA torch and InstaNovo because it runs inference. This job only reads prediction
# CSVs and scores them, so it needs proteobench, s3fs and pyarrow and nothing else.
FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    DEBIAN_FRONTEND=noninteractive \
    TZ=Etc/UTC \
    SETUPTOOLS_SCM_PRETEND_VERSION_FOR_PROTEOBENCH=0.0.0+aichor \
    PIP_NO_CACHE_DIR=1

WORKDIR /workspace/ProteoBench

# git is needed because setuptools_scm derives the version from it; the pretend-version above
# covers the case where the staged tree has no .git at all.
RUN apt-get update \
    && apt-get install -yq --no-install-recommends ca-certificates git \
    && rm -rf /var/lib/apt/lists/*

COPY . /workspace/ProteoBench

RUN python -m pip install --upgrade pip \
    && pip install -e . \
    && pip install s3fs pyarrow

WORKDIR /workspace/ProteoBench/aichor/internal_eval

CMD ["python", "score_runs_aichor.py", "--help"]
