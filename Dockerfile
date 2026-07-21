FROM python:3.12-slim-bookworm

ARG OPENG2P_FASTAPI_COMMON_REF="git+https://github.com/OpenG2P/openg2p-fastapi-common.git#subdirectory=openg2p-fastapi-common"

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update -o Acquire::Retries=5 -o Acquire::http::Timeout=30 \
    && apt-get install -y --no-install-recommends -o Acquire::Retries=5 git \
    && rm -rf /var/lib/apt/lists/*

COPY pyproject.toml README.md ./
COPY src ./src

RUN pip install --upgrade pip \
    && pip install "${OPENG2P_FASTAPI_COMMON_REF}" \
    && pip install .

RUN adduser --disabled-password --gecos "" appuser \
    && chown -R appuser:appuser /app

USER appuser

EXPOSE 8001

CMD ["python", "-m", "openg2p_farmer_profile_dedup.main", "run"]
