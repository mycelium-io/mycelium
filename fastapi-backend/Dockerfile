FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev python3-dev curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

# Copy project metadata first for layer caching
COPY pyproject.toml ./
# Install runtime deps from pyproject.toml — agensgraph-python needs --no-build-isolation
# so install everything else first, then agensgraph-python separately.
RUN uv pip install --system --no-cache \
    "fastapi[standard]>=0.115.0,<0.116" \
    "asyncpg>=0.29.0,<0.32" \
    "pydantic-settings>=2.5.2,<3" \
    "httpx>=0.28.1" \
    "python-multipart>=0.0.9" \
    "anthropic>=0.40.0" \
    "greenlet>=3.0" \
    "psycopg2-binary>=2.9.0" \
    "negmas>=0.10.0" \
    "sentence-transformers==2.7.0" \
    "transformers<4.40" \
    "alembic>=1.14.0,<2" && \
    uv pip install --system --no-cache "setuptools" && \
    uv pip install --system --no-cache --no-build-isolation "agensgraph-python==1.0.2"

COPY . .

RUN chmod +x start.sh

EXPOSE 8000
CMD ["./start.sh"]
