FROM python:3.12-slim

# Create a dedicated app user. UID 1000 matches the default host ubuntu user,
# which keeps bind-mount ownership consistent without needing chown at runtime.
RUN useradd -r -u 1000 -g 0 -s /sbin/nologin -d /home/mycelium mycelium \
    && mkdir -p /home/mycelium \
    && chown mycelium /home/mycelium

WORKDIR /app

RUN apt-get update && apt-get install -y --no-install-recommends \
    gcc libpq-dev python3-dev curl \
    && rm -rf /var/lib/apt/lists/*

RUN pip install uv

# Copy project metadata first for layer caching
COPY pyproject.toml uv.lock ./
# Install all runtime deps from pyproject.toml (excluding agensgraph which needs --no-build-isolation)
RUN python3 -c 'import tomllib; deps=tomllib.load(open("pyproject.toml","rb"))["project"]["dependencies"]; print("\n".join(d for d in deps if "agensgraph" not in d))' > /tmp/requirements.txt && \
    uv pip install --system --no-cache -r /tmp/requirements.txt && \
    uv pip install --system --no-cache "setuptools" && \
    uv pip install --system --no-cache --no-build-isolation "agensgraph-python==1.0.2"

COPY . .

# Pre-download ONNX embedding model so the container starts without any
# network dependency. fastembed uses BAAI/bge-small-en-v1.5 (384-dim, ONNX, ~50MB).
# Cache to /opt/fastembed so it's not shadowed by volume mounts on /root.
ENV FASTEMBED_CACHE_PATH=/opt/fastembed
RUN python3 -c "from fastembed import TextEmbedding; TextEmbedding(model_name='BAAI/bge-small-en-v1.5', cache_dir='/opt/fastembed')" || true

RUN chmod +x start.sh \
    && mkdir -p logs \
    && chown -R mycelium /app

USER mycelium

EXPOSE 8000
CMD ["./start.sh"]
