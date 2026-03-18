FROM python:3.12-slim

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev python3-dev curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

# Copy project metadata first for layer caching
COPY pyproject.toml uv.lock ./
# Install all runtime deps from pyproject.toml (excluding agensgraph which needs --no-build-isolation)
RUN uv pip install --system --no-cache \
        $(python3 -c "import tomllib; deps=tomllib.load(open('pyproject.toml','rb'))['project']['dependencies']; print(' '.join(repr(d) for d in deps if 'agensgraph' not in d))") && \
    uv pip install --system --no-cache "setuptools" && \
    uv pip install --system --no-cache --no-build-isolation "agensgraph-python==1.0.2"

COPY . .

# Pre-download embedding model weights so the container starts without any
# network dependency. This is a stable layer — only rebuilt when the base
# image or deps change.
RUN python3 -c "from sentence_transformers import SentenceTransformer; SentenceTransformer('sentence-transformers/all-MiniLM-L6-v2')"

RUN chmod +x start.sh

EXPOSE 8000
CMD ["./start.sh"]
