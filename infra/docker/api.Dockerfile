# API image.
#
# BUILD FROM THE REPOSITORY ROOT, not from backend/:
#
#     docker build -f infra/docker/api.Dockerfile -t gba-api .
#
# The context has to be the root because the app reads its data from
# `data/processed/` and `ml/artifacts/`, which are siblings of `backend/`.
# Services locate them with `Path(__file__).parents[3]`, so the directory
# layout inside the image must mirror the repository:
#
#     /app/backend/app/services/flood.py   ->  parents[3] == /app
#     /app/data/processed/                 <-  therefore found here
#
# An earlier version of this file used `context: ./backend`, which produced a
# container that started cleanly and resolved its data directory to `/data` —
# a path that did not exist. Every jurisdiction lookup failed with no build
# error to explain why. Hence the explicit note.

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    PIP_NO_CACHE_DIR=1

WORKDIR /app

RUN apt-get update \
 && apt-get install -y --no-install-recommends build-essential libpq-dev curl \
 && rm -rf /var/lib/apt/lists/*

# The package source is needed for an editable install, so the whole backend
# is copied before pip runs. Dependencies change rarely; if build time becomes
# a problem, split pyproject.toml into its own layer with a non-editable install.
COPY backend/ backend/
RUN pip install --upgrade pip && pip install -e "./backend[dev]"

# Processed layers and ML metrics are committed and small enough to bake in.
# Together these are what let the app answer without a database.
COPY data/processed/ data/processed/
COPY ml/artifacts/ ml/artifacts/

# Trained models (~176 MB) are NOT committed and NOT baked in. Without them the
# app still serves jurisdiction, GIS, proximity, documents and every published
# metric; the endpoints that need a fitted estimator return an RFC-7807
# "data unavailable" response with a reason, which is the same honest failure
# they give locally. To enable live prediction, mount them:
#
#     docker run -p 8000:8000 -v "$(pwd)/models:/app/models:ro" gba-api
#
# or run `python scripts/bootstrap.py --train` and rebuild.
VOLUME ["/app/models"]

WORKDIR /app/backend
ENV PYTHONPATH=/app/backend

EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --retries=3 \
  CMD curl -fsS http://localhost:8000/health || exit 1

CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
