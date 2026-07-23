# ComfyUI + Trellis2 (image-to-3D) engine image.
#
# Base: yanwk/comfyui-boot:cu130-slim-v2
#   Rocky Linux 10 · Python 3.13 (cp313) · Torch 2.12.0+cu130 · CUDA 13.0
#
# Adds the visualbruno/ComfyUI-Trellis2 custom node plus its compiled CUDA
# extensions (cumesh, flex_gemm, nvdiffrast, nvdiffrec_render, o_voxel) and the
# Python deps the node needs at runtime.
#
# Notes on the wheel choice:
#   The repo ships Linux cp313 wheels only under wheels/Linux/Torch2110 (built
#   against Torch 2.11.0). They import and run cleanly against the base image's
#   Torch 2.12.0 (validated), so we do NOT downgrade torch.
#
# The DINOv3 weights (facebook/dinov3-vitl16-pretrain-lvd1689m) and the TRELLIS.2
# model are NOT baked in; they are supplied at runtime via the shared
# /data/models volume (see docker-compose.yml).
FROM yanwk/comfyui-boot:cu130-slim-v2

# TRELLIS defaults its attention backend to flash_attn, which we do not ship
# (no prebuilt flash-attn / xformers for cu130). Fall back to torch's built-in
# scaled_dot_product_attention, which is always available. Override at runtime
# by setting ATTN_BACKEND (xformers | flash_attn | flash_attn_3 | sdpa | naive).
ENV ATTN_BACKEND=sdpa

ARG NODE_DIR=/default-comfyui-bundle/ComfyUI/custom_nodes/ComfyUI-Trellis2
ARG WHEELS=${NODE_DIR}/wheels/Linux/Torch2110

# Freeze the base image's torch stack so nothing below can replace it.
COPY torch-constraints.txt /tmp/torch-constraints.txt

# 1. Custom node into the ComfyUI *bundle*. The base image's runner copies
#    /default-comfyui-bundle/ComfyUI -> /root/ComfyUI on boot, so the node must
#    live in the bundle to survive container recreation.
RUN git clone --depth 1 https://github.com/visualbruno/ComfyUI-Trellis2.git ${NODE_DIR}

# 2. Prebuilt cp313 CUDA extensions. --no-deps because their metadata declares a
#    loose `torch>=2.4` we don't want pip to re-resolve against the index.
RUN python3.13 -m pip install --no-cache-dir --no-deps \
      ${WHEELS}/cumesh-1.0-cp313-cp313-linux_x86_64.whl \
      ${WHEELS}/flex_gemm-1.0.0-cp313-cp313-linux_x86_64.whl \
      ${WHEELS}/nvdiffrast-0.4.0-cp313-cp313-linux_x86_64.whl \
      ${WHEELS}/nvdiffrec_render-0.0.0-cp313-cp313-linux_x86_64.whl \
      ${WHEELS}/o_voxel-0.0.1-cp313-cp313-linux_x86_64.whl

# 3. Node requirements + undeclared runtime deps, with the torch stack frozen.
#      requirements.txt : meshlib, pymeshlab, opencv-python, scipy, open3d,
#                         plotly, rembg, requests
#      plyfile, zstandard : imported by o_voxel but declared nowhere
#      utils3d            : the EasternJournalist git package. The PyPI project
#                           named "utils3d" is unrelated; TRELLIS needs this repo
#                           pinned to the commit that still exposes utils3d.torch.*
#
#    open3d is intentionally stripped: it publishes no cp313 wheel (tops out at
#    cp312) and is only imported lazily inside two optional mesh-cleanup paths:
#      - the merge_vertices / remove_nan_vertices toggle of the post-process node
#      - the Laplacian/Taubin "Smooth Mesh" node
#    The node still loads and the core image-to-3D pipeline runs without it; only
#    those two features raise ImportError if explicitly enabled.
RUN grep -ivE '^[[:space:]]*open3d' ${NODE_DIR}/requirements.txt > /tmp/trellis-reqs.txt && \
    python3.13 -m pip install --no-cache-dir -c /tmp/torch-constraints.txt \
      -r /tmp/trellis-reqs.txt \
      plyfile zstandard \
      "utils3d @ git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8"

# 4. Drop the bundled wheel payloads (Windows + other torch versions) now that
#    the Linux cp313 set is installed, to keep the image lean.
RUN rm -rf ${NODE_DIR}/wheels
