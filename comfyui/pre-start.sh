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

# --- ComfyUI-LTXVideo (LTX-2.3 audio/video nodes: NAG, AV latent, encoders) --
# Provides the LTX-2.3 nodes the i2v and MSR workflows depend on (LTX2_NAG,
# LTXVConcatAVLatent, LTXAVTextEncoderLoader, LTXVAudioVAELoader, ...). Clone
# only: its other requirements (diffusers, einops, transformers[timm],
# huggingface_hub, ninja) are already provided by the megapak base image and the
# node imports cleanly against them. We deliberately do NOT run its
# requirements.txt -- forcing transformers[timm]/diffusers --user could shadow
# the versions Trellis2 and other nodes here rely on. Its one genuine
# incompatibility (kornia 0.8.3 dropping pyramid.pad) is handled by the pin
# block immediately below.
LTXV_NODE_DIR=/root/ComfyUI/custom_nodes/ComfyUI-LTXVideo
LTXV_REPO_URL=https://github.com/Lightricks/ComfyUI-LTXVideo.git

if [ -d "${LTXV_NODE_DIR}/.git" ]; then
    log "ComfyUI-LTXVideo already present at ${LTXV_NODE_DIR} (skipping clone)."
else
    log "Cloning ComfyUI-LTXVideo into ${LTXV_NODE_DIR}..."
    rm -rf "${LTXV_NODE_DIR:?}"/* "${LTXV_NODE_DIR:?}"/.[!.]* 2>/dev/null
    if git clone --depth 1 "${LTXV_REPO_URL}" "${LTXV_NODE_DIR}"; then
        log "Clone succeeded."
    else
        log "WARNING: git clone failed (offline / GitHub unreachable?)." \
            "ComfyUI-LTXVideo will NOT load this boot; ComfyUI itself will still start."
    fi
fi

# --- kornia pin for ComfyUI-LTXVideo -----------------------------------------
# ComfyUI-LTXVideo (cloned above; provides the LTX-2.3 audio/video nodes the
# MSR + i2v workflows need) does
# `from kornia.geometry.transform.pyramid import pad`. kornia 0.8.3 dropped that
# re-export (pad now comes from torch F.pad internally), so the whole node pack
# fails to import against the base image's shipped 0.8.3. 0.8.2 is the highest
# release that still exports it. Install --user (shadows the system kornia for
# root, like every other dep here), pinned against torch-constraints so it can't
# drag torch/numpy along. Guarded on the exact failing import so steady-state
# boots skip it.
if [ -d /root/ComfyUI/custom_nodes/ComfyUI-LTXVideo ] && \
   ! python3.13 -c "from kornia.geometry.transform.pyramid import pad" >/dev/null 2>&1; then
    log "ComfyUI-LTXVideo needs kornia<=0.8.2 (system kornia dropped pyramid.pad) -- pinning 0.8.2."
    KORNIA_CONSTRAINT_ARGS=()
    [ -f "${CONSTRAINTS}" ] && KORNIA_CONSTRAINT_ARGS=(-c "${CONSTRAINTS}")
    if python3.13 -m pip install --user --no-cache-dir "${KORNIA_CONSTRAINT_ARGS[@]}" "kornia==0.8.2"; then
        log "kornia 0.8.2 installed for ComfyUI-LTXVideo."
    else
        log "WARNING: kornia 0.8.2 install failed; ComfyUI-LTXVideo will not load this boot."
    fi
fi

# --- ComfyUI-Licon-MSR (LTX-2.3 Multiple-Subject-Reference conditioning) -----
# Pure-Python node (module `licon_msr`); only dep is opencv-python, already in
# the base image. Backs the "Licon MSR" node that composes multiple subject
# reference images + a background into the fixed-frame reference video LTX-2.3
# MSR workflows consume. No models of its own.
# Pinned to a verified-working commit for reproducibility: clone if missing,
# then enforce the SHA even on a persisted volume (a future SHA bump takes
# effect on next boot; steady state is a single rev-parse, no network).
MSR_NODE_DIR=/root/ComfyUI/custom_nodes/ComfyUI-Licon-MSR
MSR_REPO_URL=https://github.com/liconstudio/ComfyUI-Licon-MSR.git
MSR_SHA=94a52bfec735ff6f802c480f7fe8fdac1d279a7f

if [ ! -d "${MSR_NODE_DIR}/.git" ]; then
    log "Cloning ComfyUI-Licon-MSR into ${MSR_NODE_DIR}..."
    rm -rf "${MSR_NODE_DIR:?}"/* "${MSR_NODE_DIR:?}"/.[!.]* 2>/dev/null
    git clone "${MSR_REPO_URL}" "${MSR_NODE_DIR}" \
        || log "WARNING: git clone failed (offline?); ComfyUI-Licon-MSR will not load this boot."
fi
if [ -d "${MSR_NODE_DIR}/.git" ] && \
   [ "$(git -C "${MSR_NODE_DIR}" rev-parse HEAD 2>/dev/null)" != "${MSR_SHA}" ]; then
    log "Pinning ComfyUI-Licon-MSR to ${MSR_SHA}..."
    git -C "${MSR_NODE_DIR}" fetch --depth 1 origin "${MSR_SHA}" 2>/dev/null \
        && git -C "${MSR_NODE_DIR}" checkout -q "${MSR_SHA}" \
        || log "WARNING: could not check out pinned Licon-MSR SHA (offline / SHA unreachable?)."
fi

# opencv-python is already provided by the base image; install (guarded) only
# if cv2 is somehow missing, pinned against torch-constraints so it can't drag
# in a conflicting torch/numpy.
if [ -d "${MSR_NODE_DIR}/.git" ] && ! python3.13 -c "import cv2" >/dev/null 2>&1; then
    MSR_CONSTRAINT_ARGS=()
    [ -f "${CONSTRAINTS}" ] && MSR_CONSTRAINT_ARGS=(-c "${CONSTRAINTS}")
    if python3.13 -m pip install --user --no-cache-dir "${MSR_CONSTRAINT_ARGS[@]}" opencv-python; then
        log "opencv-python installed for ComfyUI-Licon-MSR."
    else
        log "WARNING: opencv-python install failed; Licon MSR node may not load."
    fi
fi

# --- ComfyUI_Comfyroll_CustomNodes (provides "CR Float To Integer" etc.) ------
# Pure-Python utility pack; the MSR workflow uses its CR Float To Integer node.
# Ships no requirements.txt -- its deps (numpy, Pillow, matplotlib, torch) are
# all in the base image -- so clone only. A fresh clone also supersedes any
# stale copy ComfyUI-Manager flagged as outdated.
CR_NODE_DIR=/root/ComfyUI/custom_nodes/ComfyUI_Comfyroll_CustomNodes
CR_REPO_URL=https://github.com/Suzie1/ComfyUI_Comfyroll_CustomNodes.git
CR_SHA=d78b780ae43fcf8c6b7c6505e6ffb4584281ceca

if [ ! -d "${CR_NODE_DIR}/.git" ]; then
    log "Cloning ComfyUI_Comfyroll_CustomNodes into ${CR_NODE_DIR}..."
    rm -rf "${CR_NODE_DIR:?}"/* "${CR_NODE_DIR:?}"/.[!.]* 2>/dev/null
    git clone "${CR_REPO_URL}" "${CR_NODE_DIR}" \
        || log "WARNING: git clone failed (offline?); Comfyroll will not load this boot."
fi
if [ -d "${CR_NODE_DIR}/.git" ] && \
   [ "$(git -C "${CR_NODE_DIR}" rev-parse HEAD 2>/dev/null)" != "${CR_SHA}" ]; then
    log "Pinning ComfyUI_Comfyroll_CustomNodes to ${CR_SHA}..."
    git -C "${CR_NODE_DIR}" fetch --depth 1 origin "${CR_SHA}" 2>/dev/null \
        && git -C "${CR_NODE_DIR}" checkout -q "${CR_SHA}" \
        || log "WARNING: could not check out pinned Comfyroll SHA (offline / SHA unreachable?)."
fi

# --- ComfyUI-PromptRelay (provides PromptRelayEncode) -------------------------
# kijai's prompt-relay nodes; the MSR workflow uses PromptRelayEncode. Only
# non-base dep is word2number (declared in its requirements.txt). Install
# --user, guarded on the import, pinned against torch-constraints.
PR_NODE_DIR=/root/ComfyUI/custom_nodes/ComfyUI-PromptRelay
PR_REPO_URL=https://github.com/kijai/ComfyUI-PromptRelay.git
PR_SHA=ca5d4e3edb6abd9c2a4c68a3a6798eec1980f450

if [ ! -d "${PR_NODE_DIR}/.git" ]; then
    log "Cloning ComfyUI-PromptRelay into ${PR_NODE_DIR}..."
    rm -rf "${PR_NODE_DIR:?}"/* "${PR_NODE_DIR:?}"/.[!.]* 2>/dev/null
    git clone "${PR_REPO_URL}" "${PR_NODE_DIR}" \
        || log "WARNING: git clone failed (offline?); ComfyUI-PromptRelay will not load this boot."
fi
if [ -d "${PR_NODE_DIR}/.git" ] && \
   [ "$(git -C "${PR_NODE_DIR}" rev-parse HEAD 2>/dev/null)" != "${PR_SHA}" ]; then
    log "Pinning ComfyUI-PromptRelay to ${PR_SHA}..."
    git -C "${PR_NODE_DIR}" fetch --depth 1 origin "${PR_SHA}" 2>/dev/null \
        && git -C "${PR_NODE_DIR}" checkout -q "${PR_SHA}" \
        || log "WARNING: could not check out pinned PromptRelay SHA (offline / SHA unreachable?)."
fi

if [ -d "${PR_NODE_DIR}/.git" ] && ! python3.13 -c "import word2number" >/dev/null 2>&1; then
    PR_CONSTRAINT_ARGS=()
    [ -f "${CONSTRAINTS}" ] && PR_CONSTRAINT_ARGS=(-c "${CONSTRAINTS}")
    if python3.13 -m pip install --user --no-cache-dir "${PR_CONSTRAINT_ARGS[@]}" "word2number==1.1"; then
        log "word2number installed for ComfyUI-PromptRelay."
    else
        log "WARNING: word2number install failed; PromptRelayEncode may not load."
    fi
fi

# --- ComfyUI-WanAnimatePlus (SCAIL-2 / WanAnimate character animation) --------
# WanVideoWrapper-style fork providing WanAnimatePlus* nodes incl. the SCAIL_2
# Flow Sampler / SCAIL_2 Embeds for single- & multi-reference character
# animation. Most deps (diffusers, accelerate, peft, sentencepiece, ftfy,
# einops, scipy, gguf, opencv) are already in the base image; only protobuf +
# pyloudnorm are missing. Pinned to a verified commit on its own named volume.
WAP_NODE_DIR=/root/ComfyUI/custom_nodes/ComfyUI-WanAnimatePlus
WAP_REPO_URL=https://github.com/wuwukaka/ComfyUI-WanAnimatePlus.git
WAP_SHA=4327a9fceda22dae545969603e91bc7d7adb0bdc

if [ ! -d "${WAP_NODE_DIR}/.git" ]; then
    log "Cloning ComfyUI-WanAnimatePlus into ${WAP_NODE_DIR}..."
    rm -rf "${WAP_NODE_DIR:?}"/* "${WAP_NODE_DIR:?}"/.[!.]* 2>/dev/null
    git clone "${WAP_REPO_URL}" "${WAP_NODE_DIR}" \
        || log "WARNING: git clone failed (offline?); ComfyUI-WanAnimatePlus will not load this boot."
fi
if [ -d "${WAP_NODE_DIR}/.git" ] && \
   [ "$(git -C "${WAP_NODE_DIR}" rev-parse HEAD 2>/dev/null)" != "${WAP_SHA}" ]; then
    log "Pinning ComfyUI-WanAnimatePlus to ${WAP_SHA}..."
    git -C "${WAP_NODE_DIR}" fetch --depth 1 origin "${WAP_SHA}" 2>/dev/null \
        && git -C "${WAP_NODE_DIR}" checkout -q "${WAP_SHA}" \
        || log "WARNING: could not check out pinned WanAnimatePlus SHA (offline / SHA unreachable?)."
fi

if [ -d "${WAP_NODE_DIR}/.git" ] && \
   ! python3.13 -c "import google.protobuf, pyloudnorm" >/dev/null 2>&1; then
    WAP_CONSTRAINT_ARGS=()
    [ -f "${CONSTRAINTS}" ] && WAP_CONSTRAINT_ARGS=(-c "${CONSTRAINTS}")
    if python3.13 -m pip install --user --no-cache-dir "${WAP_CONSTRAINT_ARGS[@]}" protobuf pyloudnorm; then
        log "protobuf + pyloudnorm installed for ComfyUI-WanAnimatePlus."
    else
        log "WARNING: protobuf/pyloudnorm install failed; WanAnimatePlus may not load."
    fi
fi

# --- ComfyUI-CustomNodeKit (SCAIL-2 multi-reference workflow + pose/masking) ---
# Exposes the native Wan/SCAIL-2 nodes as a multi-ref workflow (Wan SCAIL To
# Video (Multi Ref), clip_vision_multiref, context mgmt) plus SDPose/GroundingDINO
# auto-masking helpers. Base image already has opencv, imageio-ffmpeg,
# transformers, groundingdino-py, tqdm; only mediapipe is missing. Pinned to
# mediapipe 0.10.35 (newest 0.10.x) rather than 1.0.0 -- the SDPose nodes target
# the 0.10 API. Pinned SHA on its own named volume.
CNK_NODE_DIR=/root/ComfyUI/custom_nodes/ComfyUI-CustomNodeKit
CNK_REPO_URL=https://github.com/user2318/ComfyUI-CustomNodeKit.git
CNK_SHA=78c85ad3a352d5b864b3351846bcf88d2325c5ff

if [ ! -d "${CNK_NODE_DIR}/.git" ]; then
    log "Cloning ComfyUI-CustomNodeKit into ${CNK_NODE_DIR}..."
    rm -rf "${CNK_NODE_DIR:?}"/* "${CNK_NODE_DIR:?}"/.[!.]* 2>/dev/null
    git clone "${CNK_REPO_URL}" "${CNK_NODE_DIR}" \
        || log "WARNING: git clone failed (offline?); ComfyUI-CustomNodeKit will not load this boot."
fi
if [ -d "${CNK_NODE_DIR}/.git" ] && \
   [ "$(git -C "${CNK_NODE_DIR}" rev-parse HEAD 2>/dev/null)" != "${CNK_SHA}" ]; then
    log "Pinning ComfyUI-CustomNodeKit to ${CNK_SHA}..."
    git -C "${CNK_NODE_DIR}" fetch --depth 1 origin "${CNK_SHA}" 2>/dev/null \
        && git -C "${CNK_NODE_DIR}" checkout -q "${CNK_SHA}" \
        || log "WARNING: could not check out pinned CustomNodeKit SHA (offline / SHA unreachable?)."
fi

if [ -d "${CNK_NODE_DIR}/.git" ] && ! python3.13 -c "import mediapipe" >/dev/null 2>&1; then
    CNK_CONSTRAINT_ARGS=()
    [ -f "${CONSTRAINTS}" ] && CNK_CONSTRAINT_ARGS=(-c "${CONSTRAINTS}")
    if python3.13 -m pip install --user --no-cache-dir "${CNK_CONSTRAINT_ARGS[@]}" "mediapipe==0.10.35"; then
        log "mediapipe 0.10.35 installed for ComfyUI-CustomNodeKit."
    else
        log "WARNING: mediapipe install failed; CustomNodeKit pose/masking nodes may not load."
    fi
fi

# --- Krea2 T2I/I2I/Inpaint workflow node packs -------------------------------
# Three pure-Python node packs the Krea2 2-pass workflow needs, none of which
# ship a requirements.txt (all deps are in the base image), so each is a
# clone-and-pin, same shape as Comfyroll/PromptRelay above:
#   - comfyui-mxtoolkit         mxSlider (step/denoise sliders)
#   - ComfyUI-krea2-negpip      ApplyKrea2NegPiP (negative-weight prompt tokens)
#   - ComfyUI-Krea2T-Enhancer   ComfyUI-Krea2T-Enhancer (seed enhancer/jazz-up)
# negpip + enhancer are pinned to the exact SHAs the shipped workflow JSON was
# exported against; mxToolkit has no releases/tags so it tracks a pinned HEAD.
# rgthree-comfy (Power Lora Loader / Any Switch / Image Comparer), comfyui-easy-use
# (easy seed/float/simpleMath), comfyui-image-saver (Image Saver Simple) and
# RES4LYF (ClownsharKSampler_Beta) are already present in the base image.
for spec in \
    "comfyui-mxtoolkit|https://github.com/Smirnov75/ComfyUI-mxToolkit.git|7f7a0e584f12078a1c589645d866ae96bad0cc35" \
    "ComfyUI-krea2-negpip|https://github.com/blue-pen5805/ComfyUI-krea2-negpip.git|3740add9dbdc9f254a2befda30e95ba95e3b115d" \
    "ComfyUI-Krea2T-Enhancer|https://github.com/capitan01R/ComfyUI-Krea2T-Enhancer.git|cf8895005540680306cd46e1faaf75f8902db794"; do
    K2_NAME="${spec%%|*}"; K2_REST="${spec#*|}"
    K2_URL="${K2_REST%%|*}"; K2_SHA="${K2_REST##*|}"
    K2_DIR="/root/ComfyUI/custom_nodes/${K2_NAME}"

    if [ ! -d "${K2_DIR}/.git" ]; then
        log "Cloning ${K2_NAME} into ${K2_DIR}..."
        rm -rf "${K2_DIR:?}"/* "${K2_DIR:?}"/.[!.]* 2>/dev/null
        git clone "${K2_URL}" "${K2_DIR}" \
            || log "WARNING: git clone failed (offline?); ${K2_NAME} will not load this boot."
    fi
    if [ -d "${K2_DIR}/.git" ] && \
       [ "$(git -C "${K2_DIR}" rev-parse HEAD 2>/dev/null)" != "${K2_SHA}" ]; then
        log "Pinning ${K2_NAME} to ${K2_SHA}..."
        git -C "${K2_DIR}" fetch --depth 1 origin "${K2_SHA}" 2>/dev/null \
            && git -C "${K2_DIR}" checkout -q "${K2_SHA}" \
            || log "WARNING: could not check out pinned ${K2_NAME} SHA (offline / SHA unreachable?)."
    fi
done

# --- ComfyUI-KJNodes (provides ColorMatch) -----------------------------------
# kijai's utility pack; the colour-match post pass (image_color_match) uses its
# ColorMatch node (image_ref/image_target/method). Deps are in the base image;
# clone-only, same shape as Comfyroll above.
KJ_NODE_DIR=/root/ComfyUI/custom_nodes/ComfyUI-KJNodes
KJ_REPO_URL=https://github.com/kijai/ComfyUI-KJNodes.git

if [ ! -d "${KJ_NODE_DIR}/.git" ]; then
    log "Cloning ComfyUI-KJNodes into ${KJ_NODE_DIR}..."
    rm -rf "${KJ_NODE_DIR:?}"/* "${KJ_NODE_DIR:?}"/.[!.]* 2>/dev/null
    git clone --depth 1 "${KJ_REPO_URL}" "${KJ_NODE_DIR}" \
        || log "WARNING: git clone failed (offline?); ComfyUI-KJNodes will not load this boot."
fi
if [ -d "${KJ_NODE_DIR}/requirements.txt" ] 2>/dev/null; then :; fi
if [ -d "${KJ_NODE_DIR}/.git" ] && [ -f "${KJ_NODE_DIR}/requirements.txt" ]; then
    KJ_CONSTRAINT_ARGS=()
    [ -f "${CONSTRAINTS}" ] && KJ_CONSTRAINT_ARGS=(-c "${CONSTRAINTS}")
    python3.13 -m pip install --user --no-cache-dir "${KJ_CONSTRAINT_ARGS[@]}" \
        -r "${KJ_NODE_DIR}/requirements.txt" \
        || log "WARNING: KJNodes requirements install failed; some KJ nodes may not load."
fi

# --- ComfyUI-ProPost (provides ProPostFilmGrain) -----------------------------
# Optional film-grain pass appended after colour match (image_color_match).
PP_NODE_DIR=/root/ComfyUI/custom_nodes/ComfyUI-ProPost
PP_REPO_URL=https://github.com/digitaljohn/comfyui-propost.git

if [ ! -d "${PP_NODE_DIR}/.git" ]; then
    log "Cloning ComfyUI-ProPost into ${PP_NODE_DIR}..."
    rm -rf "${PP_NODE_DIR:?}"/* "${PP_NODE_DIR:?}"/.[!.]* 2>/dev/null
    git clone --depth 1 "${PP_REPO_URL}" "${PP_NODE_DIR}" \
        || log "WARNING: git clone failed (offline?); ComfyUI-ProPost will not load this boot."
fi
if [ -d "${PP_NODE_DIR}/.git" ] && [ -f "${PP_NODE_DIR}/requirements.txt" ]; then
    PP_CONSTRAINT_ARGS=()
    [ -f "${CONSTRAINTS}" ] && PP_CONSTRAINT_ARGS=(-c "${CONSTRAINTS}")
    python3.13 -m pip install --user --no-cache-dir "${PP_CONSTRAINT_ARGS[@]}" \
        -r "${PP_NODE_DIR}/requirements.txt" \
        || log "WARNING: ProPost requirements install failed; film grain may not load."
fi

# --- Remove the base-image's duplicate lowercase ProPost copy ----------------
# The megapak base bundle ships a second copy at custom_nodes/comfyui-propost
# in addition to the ComfyUI-ProPost we manage above. Both register the SAME
# node class names (ProPostFilmGrain, ProPostVignette, ...). Custom nodes load
# alphabetically with uppercase before lowercase, so the load order is:
#   1. ComfyUI-ProPost   -> binds its own bundled `filmgrainer` package (correct)
#   2. ComfyUI_LayerStyle -> also vendors a top-level `filmgrainer` package,
#                            which now shadows sys.modules['filmgrainer']
#   3. comfyui-propost   -> re-imports `filmgrainer` (now LayerStyle's, whose
#                            process() expects a PIL Image not a numpy array) and
#                            OVERWRITES the good ProPostFilmGrain registration.
# Net effect: ProPostFilmGrain crashes with "'int' object is not subscriptable".
# Deleting the redundant lowercase copy leaves only ComfyUI-ProPost, which loads
# before LayerStyle and binds its own filmgrainer correctly. Guarded so it's a
# one-time no-op on steady-state boots.
PP_DUP_DIR=/root/ComfyUI/custom_nodes/comfyui-propost
if [ -e "${PP_DUP_DIR}" ]; then
    log "Removing duplicate base-image ProPost copy at ${PP_DUP_DIR} (shadows filmgrainer, breaks ProPostFilmGrain)."
    rm -rf "${PP_DUP_DIR}" || log "WARNING: could not remove ${PP_DUP_DIR}; ProPostFilmGrain may crash."
fi

# --- ComfyUI-ProPost filmgrainer-shadowing patch -----------------------------
# Even with the lowercase duplicate gone, ComfyUI_LayerStyle vendors its OWN
# top-level package named `filmgrainer` (at ComfyUI_LayerStyle/py/filmgrainer)
# and gets it into sys.modules first. ProPost's `nodes.py` does a bare
# `import filmgrainer.filmgrainer` after only `sys.path.append(...)`, so it
# binds LayerStyle's copy -- whose process() expects a PIL Image and dies on
# ProPost's numpy array with "'int' object is not subscriptable", crashing
# ProPostFilmGrain. Patch nodes.py to insert its own dir at the FRONT of
# sys.path and drop any cached `filmgrainer*` modules immediately before the
# import, so it always binds its own bundled copy. Guarded/idempotent; survives
# an upstream re-clone.
PP_NODES=/root/ComfyUI/custom_nodes/ComfyUI-ProPost/nodes.py
if [ -f "${PP_NODES}" ] && ! grep -q "Force ProPost's own bundled" "${PP_NODES}"; then
    log "Patching ComfyUI-ProPost/nodes.py to force its own filmgrainer (avoid LayerStyle shadow)..."
    python3.13 - "${PP_NODES}" <<'PYEOF' && log "ProPost filmgrainer patched." || log "WARNING: ProPost filmgrainer patch failed; ProPostFilmGrain may crash."
import sys
p = sys.argv[1]
s = open(p).read()
old = "sys.path.append(current_file_directory)\n\nimport filmgrainer.filmgrainer as filmgrainer"
new = (
    "sys.path.insert(0, current_file_directory)\n\n"
    "# Force ProPost's own bundled filmgrainer, not the same-named package\n"
    "# vendored by ComfyUI_LayerStyle (whose process() expects a PIL Image and\n"
    "# crashes on ProPost's numpy input with 'int' object is not subscriptable).\n"
    "for _m in [m for m in list(sys.modules) if m == 'filmgrainer' or m.startswith('filmgrainer.')]:\n"
    "    del sys.modules[_m]\n"
    "import filmgrainer.filmgrainer as filmgrainer"
)
if old in s:
    open(p, "w").write(s.replace(old, new, 1))
else:
    sys.exit(1)
PYEOF
fi

# --- ComfyUI-krea2-negpip compatibility patch --------------------------------
# Its DIFFUSION_MODEL wrapper hardcodes 6 positional params, but ComfyUI 0.30.0's
# Krea2 model forward passes a 7th ("krea2_negpip_wrapper() takes from 4 to 6
# positional arguments but 7 were given"). Add a *extra passthrough to the
# wrapper signature and its inline executor() forwards. Guarded on the unpatched
# signature so it's a one-time idempotent edit that also survives a future
# upstream SHA bump.
NEGPIP_SRC=/root/ComfyUI/custom_nodes/ComfyUI-krea2-negpip/krea2_negpip.py
if [ -f "${NEGPIP_SRC}" ] && \
   grep -q 'transformer_options=None, \*\*kwargs):' "${NEGPIP_SRC}"; then
    log "Patching ComfyUI-krea2-negpip wrapper for ComfyUI 0.30.0 (7th positional arg)..."
    if python3.13 - "${NEGPIP_SRC}" <<'PYEOF'
import re, sys
p = sys.argv[1]
s = open(p).read()
s = s.replace(
    "def krea2_negpip_wrapper(executor, x, timesteps, context, attention_mask=None, transformer_options=None, **kwargs):",
    "def krea2_negpip_wrapper(executor, x, timesteps, context, attention_mask=None, transformer_options=None, *extra, **kwargs):")
s = re.sub(r"return executor\(([^\n]*?), \*\*kwargs\)", r"return executor(\1, *extra, **kwargs)", s)
open(p, "w").write(s)
PYEOF
    then
        log "krea2-negpip wrapper patched."
    else
        log "WARNING: krea2-negpip wrapper patch failed; NegPiP node may error at sample time."
    fi
fi

log "pre-start finished."
set -e
