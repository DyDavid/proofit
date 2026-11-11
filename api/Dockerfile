# ═══════════════════════════════════════════════════════════════════════════
# Proofit — FastAPI service image.
#
# Build context is the REPOSITORY ROOT, not ./api — see .dockerignore's header
# comment for why. Both consumers use that pairing:
#   deploy/docker-compose.yml   context: ..   dockerfile: api/Dockerfile
#   deploy/render.yaml          dockerContext: .   dockerfilePath: ./api/Dockerfile
#
# `pip install .` installs `engine` as a real package (so engine/country/*.json
# and engine/rewrite/*.json ship via package-data — see pyproject.toml). `api/`
# itself is not pip-installed: it is copied in next to the installed `engine`
# package and imported by uvicorn relative to WORKDIR, the same way
# `uvicorn api.main:app` already works when run locally from the repo root.
#
# No compiler stage: every dependency in pyproject.toml's `api` and `parse`
# extras ships a manylinux wheel for cp312 (pydantic-core, uvicorn's
# uvloop/httptools included), so python:3.12-slim never needs build-essential.
# That keeps the image small on Render's 512 MB free instance.
# ═══════════════════════════════════════════════════════════════════════════

FROM python:3.12-slim

WORKDIR /app

# Packaging metadata + the engine package itself first, so this layer is
# cached until a dependency or engine source file actually changes.
COPY pyproject.toml README.md ./
COPY engine ./engine

# `api` extra: fastapi, uvicorn, pydantic-settings, anthropic, supabase, httpx.
# `parse` extra: pdfminer.six, python-docx — resume/JD text extraction.
RUN pip install --no-cache-dir ".[api,parse]"

# The FastAPI application itself. Not pip-installed — see header comment.
COPY api ./api

# ENGINE_MODE=mock reads these at request time (data/resumes/raw/ and eval/
# are excluded by .dockerignore; everything else under data/ ships).
COPY data ./data

# Unbuffered stdout, or `render`/`docker compose logs -f` sit behind a pipe
# buffer and look frozen.
ENV PYTHONUNBUFFERED=1

# Run as an unprivileged user, matching web/Dockerfile's posture.
RUN groupadd --system app && useradd --system --gid app app \
 && chown -R app:app /app
USER app

EXPOSE 8000

# Shell form deliberately: Render injects $PORT at runtime and the exec form
# cannot expand it. Falls back to 8000 so a bare `docker run` (no PORT set)
# still works, matching docker-compose.yml's explicit PORT=8000.
CMD ["sh", "-c", "uvicorn api.main:app --host 0.0.0.0 --port ${PORT:-8000}"]
