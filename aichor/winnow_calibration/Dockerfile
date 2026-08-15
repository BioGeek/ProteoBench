# Winnow calibration/FDR analysis of the InstaNovo v1.2.2 sweep, with Koina running
# in-pod rather than against the public server.
#
# The upstream Koina image bakes Triton together with all Koina model definitions;
# weights are fetched from Zenodo on first start. Running it beside the analysis avoids
# ~5.5M remote predictions (7 modes x 779,879 spectra) against a shared public service.
#
# Structure follows winnow's own Dockerfile.koina (instadeepai/winnow, `revisions`
# branch): same base image, same readiness handshake, same model-subset pin. Winnow
# itself is installed from PyPI so this image does not have to vendor its source.
FROM ghcr.io/wilhelm-lab/koina:latest

ENV LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1

# Triton's Python-backend models import these. The published Koina image periodically
# loses them when its base tritonserver image is bumped, so pin them into the same
# system Python the backend uses.
RUN pip install --no-cache-dir \
        requests \
        numpy \
        pandas \
        pyteomics==4.6.2 \
        ms2pip==3.13 \
        psm-utils \
        rdkit==2024.3.5

RUN apt-get update && \
    apt-get install -y --no-install-recommends ca-certificates curl make git && \
    apt-get clean && rm -rf /var/lib/apt/lists/*

# uv is not in the upstream Triton image.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh && \
    mv /root/.local/bin/uv /usr/local/bin/uv && \
    mv /root/.local/bin/uvx /usr/local/bin/uvx
ENV UV_TOOL_DIR=/opt/uv-tools UV_TOOL_BIN_DIR=/usr/local/bin
RUN uv tool install awscli && aws --version

# Winnow needs a newer Python than the Triton image's system one, so give it its own
# interpreter and venv. Keep it off the system Python to avoid the Triton backend
# picking up these packages.
# Installed from a fork rather than PyPI: winnow-fdr 2.0.0 builds its Koina client as
# `koinapy.Koina(model_name)` with no server argument, so it can only ever reach the
# public endpoint. The fork adds `koina.server_url` / `koina.ssl`, which is what lets
# the features talk to the Triton instance running beside them in this image.
ARG WINNOW_SPEC="winnow-fdr @ git+https://github.com/BioGeek/winnow.git@feat/koina-server-url"
ENV UV_PROJECT_ENVIRONMENT=/opt/winnow-venv UV_PYTHON=3.12
RUN uv venv --python 3.12 /opt/winnow-venv && \
    VIRTUAL_ENV=/opt/winnow-venv uv pip install --no-cache "${WINNOW_SPEC}"
ENV PATH="/opt/winnow-venv/bin:$PATH"

# Loading every Koina model (~50+) OOMs a MIG slice. This pattern keeps the two the
# fragment-match and iRT features need. Override with -e MODEL_PATTERN=... to change it.
ENV MODEL_PATTERN="*22PTM*"

COPY entrypoint.koina.sh /usr/local/bin/entrypoint.koina.sh
COPY run_calibration.sh /usr/local/bin/run_calibration.sh
RUN chmod +x /usr/local/bin/entrypoint.koina.sh /usr/local/bin/run_calibration.sh

# Kept for plain `docker run`. AIchor replaces it by running spec.command through a
# shell, so its manifest invokes the wrapper explicitly instead of relying on this.
ENTRYPOINT ["/usr/local/bin/entrypoint.koina.sh"]
