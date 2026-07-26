# Mesh optimizer: headless Blender + gltf-transform.
# Build context is the repo root (see docker-compose.yml) so it can COPY
# scripts/bake_optimize.py alongside this service's app.
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    BLENDER_BIN=/opt/blender/blender \
    COMFY_OUTPUT_DIR=/opt/ComfyUI/output \
    BAKE_SCRIPT=/app/bake_optimize.py

# System libs Blender needs even in background mode, plus Node (for gltf-transform).
RUN apt-get update && apt-get install -y --no-install-recommends \
        wget curl xz-utils ca-certificates \
        libx11-6 libxext6 libxrender1 libxi6 libxxf86vm1 libxfixes3 \
        libxkbcommon0 libgl1 libglu1-mesa libsm6 libxrandr2 \
    && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
    && apt-get install -y --no-install-recommends nodejs \
    && npm install -g @gltf-transform/cli \
    && apt-get purge -y curl \
    && apt-get autoremove -y \
    && rm -rf /var/lib/apt/lists/*

# Blender 5.2 (matches the version validated for the bake pipeline).
RUN wget -q https://download.blender.org/release/Blender5.2/blender-5.2.0-linux-x64.tar.xz \
        -O /tmp/blender.tar.xz \
    && mkdir -p /opt/blender \
    && tar -xf /tmp/blender.tar.xz -C /opt/blender --strip-components=1 \
    && rm /tmp/blender.tar.xz \
    && /opt/blender/blender --version

WORKDIR /app
COPY optimizer/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt

# Shared with the standalone/native pipeline — one source of truth for the bake.
COPY scripts/bake_optimize.py /app/bake_optimize.py
COPY optimizer/app.py /app/app.py

EXPOSE 8300
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8300"]
