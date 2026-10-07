FROM nvidia/cuda:12.1.0-devel-ubuntu22.04 AS builder

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
ENV PIP_NO_CACHE_DIR=1

# Build dependencies. We need python3-dev for compiling the custom_rasterizer
# CUDA extension, and git for pip to fetch the requirements.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    python3-pip \
    python3-dev \
    git \
    wget \
    libgl1-mesa-glx \
    libglib2.0-0 \
    ninja-build \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

# Install Python deps in their own layer so source changes don't bust the cache.
COPY requirements.txt .
RUN pip3 install --upgrade pip \
    && pip3 install torch==2.5.1 torchvision==0.20.1 --index-url https://download.pytorch.org/whl/cu121 \
    && pip3 install -r requirements.txt

# Copy the package and opt into C++/CUDA extension compilation.
COPY . .
ARG TORCH_CUDA_ARCH_LIST="7.5;8.0;8.6;8.9;9.0"
RUN POLYFORGE_BUILD_NATIVE=1 pip3 install --no-build-isolation .

# ----------------------------------------------------------------------
# Runtime image: same base, but without the build-only tools.
# ----------------------------------------------------------------------
FROM nvidia/cuda:12.1.0-runtime-ubuntu22.04 AS runtime

ENV DEBIAN_FRONTEND=noninteractive
ENV PYTHONUNBUFFERED=1
# Don't write .pyc files in the container.
ENV PYTHONDONTWRITEBYTECODE=1

# Runtime shared libraries. The build stage already produced the
# compiled .so files inside the installed hy3dgen package, so we only
# need the system-level runtime deps here.
RUN apt-get update && apt-get install -y --no-install-recommends \
    python3 \
    libgl1 \
    libglib2.0-0 \
    && rm -rf /var/lib/apt/lists/*

# Copy the installed package (with compiled extensions) from the builder.
COPY --from=builder /usr/local/lib/python3.10/dist-packages /usr/local/lib/python3.10/dist-packages
COPY --from=builder /usr/local/bin /usr/local/bin

WORKDIR /app

# Cache and log dirs become volumes in docker-compose so they survive
# container restarts.
RUN mkdir -p /app/logs /app/.cache
ENV XDG_CACHE_HOME=/app/.cache
ENV XDG_STATE_HOME=/app/.local/state

# Backend API (when APP_MODE=api) and legacy launcher bind to 0.0.0.0
# inside the container. CORS and auth are env-driven; see
# hy3dgen/api/config.py.
EXPOSE 8081 8080

# Default to the backend. Override with APP_MODE=launcher for the legacy UI.
ENV APP_MODE=api
# Configure POLYFORGE_API_KEY before exposing the API beyond a trusted network.
ENV POLYFORGE_API_KEY=""

ENTRYPOINT ["/bin/bash", "-c"]
CMD ["if [ \"$APP_MODE\" = 'launcher' ]; then \
        exec hy3dgen-launcher --host 0.0.0.0 --port 8080; \
      else \
        exec hy3dgen-api --host 0.0.0.0; \
      fi"]
