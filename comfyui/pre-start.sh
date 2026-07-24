#!/bin/bash
# ComfyUI-Trellis2 + Texture_Projection-Nodes boot-time installer.
#
# Bind-mounted to /root/user-scripts/pre-start.sh and `source`d by the base
# image's own entrypoint (yanwk/comfyui-boot:cu130-megapak-pt211's
# /runner-scripts/entrypoint.sh) BEFORE ComfyUI starts, in the SAME shell,
# under that entrypoint's `set -e`. Two consequences that shape everything
# below:
#
#   1. Because this file is `source`d (not exec'd), a bare `exit` here would
#      kill the entrypoint's shell outright and the container would stop
#      instead of starting ComfyUI. This script never calls `exit`; it just
#      falls off the end.
#   2. Because `set -e` is inherited, any unguarded failing command aborts
#      the whole boot. The very first thing we do is `set +e` and take
#      explicit control of error handling for everything below, so that
#      expected/transient conditions (already installed, no network on a
#      repeat boot) degrade to a warning instead of a boot failure. We
#      restore `set -e` at the end for whatever the entrypoint does next.
#
# Installs into named volumes that persist independently of /root/ComfyUI's
# core tree (which the base entrypoint refreshes from /default-comfyui-bundle
# any time the relevant marker file is missing):
#   - /root/ComfyUI/custom_nodes/ComfyUI-Trellis2          node source + wheels
#   - /root/ComfyUI/custom_nodes/Texture_Projection-Nodes  node source
#   - /root/.local                                         `pip install --user` target
#
# flash-attn is NOT installed here: this base image ships it prebuilt
# (system site-packages, matching Torch 2.11.0+cu130 exactly) and
# Trellis2LoadModel's own node widgets already default to backend=flash_attn.
#
# Fast path (steady state, e.g. every boot after the first): two
# `python3.13 -c "import ..."` checks, no network calls, no filesystem writes.

set +e

NODE_DIR=/root/ComfyUI/custom_nodes/ComfyUI-Trellis2
WHEELS_DIR="${NODE_DIR}/wheels/Linux/Torch2110"
CONSTRAINTS=/root/user-scripts/torch-constraints.txt
REPO_URL=https://github.com/visualbruno/ComfyUI-Trellis2.git

# The base entrypoint sets these AFTER sourcing this script; our own pip
# calls below need them now so installs land in /root/.local (already on
# sys.path for root, never overlaps the base image's own system
# site-packages under /usr/local/lib64/python3.13/site-packages).
export PIP_USER=true
export PIP_ROOT_USER_ACTION=ignore

log() { echo "[pre-start] $*"; }

# --- 1. Fast path: is everything already importable? ------------------------
if python3.13 -c "
import cumesh, flex_gemm, nvdiffrast, nvdiffrec_render, o_voxel
import utils3d, plyfile, zstandard
" >/dev/null 2>&1; then
    log "ComfyUI-Trellis2 deps already present in /root/.local -- skipping install."
else
    log "ComfyUI-Trellis2 deps missing or incomplete -- (re)installing."

    # --- 2. Node source: clone only if missing/incomplete -------------------
    if [ -d "${NODE_DIR}/.git" ]; then
        log "Node source already present at ${NODE_DIR} (skipping clone)."
    else
        log "Cloning ComfyUI-Trellis2 into ${NODE_DIR}..."
        # Clear out any partial clone left by a previously-interrupted boot;
        # a fresh volume mount is already an empty dir, so this is a no-op
        # in the common case.
        rm -rf "${NODE_DIR:?}"/* "${NODE_DIR:?}"/.[!.]* 2>/dev/null
        if git clone --depth 1 "${REPO_URL}" "${NODE_DIR}"; then
            log "Clone succeeded."
        else
            log "WARNING: git clone failed (offline / GitHub unreachable?)." \
                "ComfyUI-Trellis2 will NOT load this boot; ComfyUI itself will still start."
        fi
    fi

    # --- 3 & 4. Wheels + requirements, only if we have node source to work with
    if [ -d "${NODE_DIR}/.git" ]; then
        # 3. Prebuilt cp313 CUDA wheels. --no-deps: their metadata declares a
        #    loose `torch>=2.4` we don't want pip re-resolving against the index.
        if ls "${WHEELS_DIR}"/*.whl >/dev/null 2>&1; then
            if python3.13 -m pip install --user --no-cache-dir --no-deps \
                "${WHEELS_DIR}"/cumesh-1.0-cp313-cp313-linux_x86_64.whl \
                "${WHEELS_DIR}"/flex_gemm-1.0.0-cp313-cp313-linux_x86_64.whl \
                "${WHEELS_DIR}"/nvdiffrast-0.4.0-cp313-cp313-linux_x86_64.whl \
                "${WHEELS_DIR}"/nvdiffrec_render-0.0.0-cp313-cp313-linux_x86_64.whl \
                "${WHEELS_DIR}"/o_voxel-0.0.1-cp313-cp313-linux_x86_64.whl; then
                log "CUDA wheels installed."
            else
                log "WARNING: CUDA wheel install failed."
            fi
        else
            log "WARNING: no wheels found under ${WHEELS_DIR} -- unexpected for a" \
                "successful clone. Node will likely fail to load this boot."
        fi

        # 4. requirements.txt (minus open3d, no cp313 wheel exists for it) +
        #    undeclared runtime deps (plyfile, zstandard, needed by o_voxel) +
        #    utils3d pinned to the EasternJournalist commit TRELLIS needs (the
        #    PyPI package named "utils3d" is an unrelated project). All pinned
        #    against torch-constraints.txt so nothing here can replace the
        #    base image's own torch/torchvision/torchaudio and break the
        #    compiled wheels' ABI.
        REQS_SRC="${NODE_DIR}/requirements.txt"
        if [ -f "${REQS_SRC}" ]; then
            TMP_REQS=$(mktemp)
            grep -ivE '^[[:space:]]*open3d' "${REQS_SRC}" > "${TMP_REQS}"

            CONSTRAINT_ARGS=()
            if [ -f "${CONSTRAINTS}" ]; then
                CONSTRAINT_ARGS=(-c "${CONSTRAINTS}")
            else
                log "WARNING: ${CONSTRAINTS} not found -- installing WITHOUT the" \
                    "torch pin. This can let a transitive dep upgrade/replace the" \
                    "base image's torch build and break the CUDA wheels' ABI."
            fi

            if python3.13 -m pip install --user --no-cache-dir "${CONSTRAINT_ARGS[@]}" \
                -r "${TMP_REQS}" \
                plyfile zstandard \
                "utils3d @ git+https://github.com/EasternJournalist/utils3d.git@9a4eb15e4021b67b12c460c7057d642626897ec8"; then
                log "Python deps installed."
            else
                log "WARNING: pip install of requirements/utils3d failed" \
                    "(offline / PyPI or GitHub unreachable?)."
            fi
            rm -f "${TMP_REQS}"
        else
            log "WARNING: ${REQS_SRC} not found -- skipping requirements install."
        fi
    fi
fi

# --- Texture_Projection-Nodes (multi-view texture baking/projection) --------
TP_NODE_DIR=/root/ComfyUI/custom_nodes/Texture_Projection-Nodes
TP_REPO_URL=https://github.com/Aero-Ex/Texture_Projection-Nodes.git
TP_RASTERIZER_DIR="${TP_NODE_DIR}/Texture_Projection/Renderer/custom_rasterizer"

# nvdiffrast/nvdiffrec_render are shared with the Trellis2 install above (same
# packages, already checked/installed there); the only genuinely new compiled
# dependency here is custom_rasterizer, vendored from Tencent Hunyuan3D under
# the Tencent Hunyuan Non-Commercial License. The repo only ships Windows
# wheels + a stale Linux .so built for cp311 (this container is cp313), so it
# must be built from source -- confirmed to compile cleanly against this
# image's nvcc/Torch 2.11.0+cu130/Python 3.13. It is not optional: MeshRender's
# only implemented raster_mode is "cr" (anything else raises ValueError), so
# both Texture_ProjectionRenderConditions and Texture_ProjectionBakeTextures
# require it to function.
if python3.13 -c "import custom_rasterizer" >/dev/null 2>&1; then
    log "Texture_Projection-Nodes deps already present in /root/.local -- skipping install."
else
    log "Texture_Projection-Nodes deps missing or incomplete -- (re)installing."

    if [ -d "${TP_NODE_DIR}/.git" ]; then
        log "Node source already present at ${TP_NODE_DIR} (skipping clone)."
    else
        log "Cloning Texture_Projection-Nodes into ${TP_NODE_DIR}..."
        rm -rf "${TP_NODE_DIR:?}"/* "${TP_NODE_DIR:?}"/.[!.]* 2>/dev/null
        if git clone --depth 1 "${TP_REPO_URL}" "${TP_NODE_DIR}"; then
            log "Clone succeeded."
        else
            log "WARNING: git clone failed (offline / GitHub unreachable?)." \
                "Texture_Projection-Nodes will NOT load this boot; ComfyUI itself will still start."
        fi
    fi

    if [ -d "${TP_NODE_DIR}/.git" ]; then
        # requirements.txt: trimesh, opencv-python, ninja -- already satisfied
        # via the base image / Trellis2's own deps today, but installed
        # explicitly here too so a fresh/wiped volume is self-sufficient.
        TP_REQS_SRC="${TP_NODE_DIR}/requirements.txt"
        if [ -f "${TP_REQS_SRC}" ]; then
            TP_CONSTRAINT_ARGS=()
            if [ -f "${CONSTRAINTS}" ]; then
                TP_CONSTRAINT_ARGS=(-c "${CONSTRAINTS}")
            else
                log "WARNING: ${CONSTRAINTS} not found -- installing WITHOUT the torch pin."
            fi
            if python3.13 -m pip install --user --no-cache-dir "${TP_CONSTRAINT_ARGS[@]}" \
                -r "${TP_REQS_SRC}"; then
                log "Texture_Projection-Nodes requirements installed."
            else
                log "WARNING: pip install of Texture_Projection-Nodes requirements failed" \
                    "(offline / PyPI unreachable?)."
            fi
        else
            log "WARNING: ${TP_REQS_SRC} not found -- skipping requirements install."
        fi

        # custom_rasterizer: build from source. --no-build-isolation is
        # required -- its setup.py imports torch directly at build time, and
        # without this flag pip's isolated build sandbox could pull a
        # different torch build just for the build step, breaking the
        # resulting extension's ABI against the image's actual torch (the
        # same trap that caused repeated breaks in the original Trellis2
        # install saga).
        if [ -d "${TP_RASTERIZER_DIR}" ]; then
            if python3.13 -m pip install --user --no-cache-dir --no-build-isolation "${TP_RASTERIZER_DIR}"; then
                log "custom_rasterizer built and installed."
            else
                log "WARNING: custom_rasterizer build failed. Texture_Projection nodes" \
                    "will not function this boot (their only raster_mode requires it)."
            fi
        else
            log "WARNING: ${TP_RASTERIZER_DIR} not found -- unexpected for a successful clone."
        fi
    fi
fi

log "pre-start finished."
set -e
