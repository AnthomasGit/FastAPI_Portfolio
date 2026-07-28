"""Standalone birefnet inference — loads the same .safetensors ComfyUI's
LoadBackgroundRemovalModel/RemoveBackground nodes use, and reproduces
comfy/bg_removal_model.py's BackgroundRemovalModel.encode_image() pipeline
(resize/normalize -> forward -> sigmoid -> resize back to original size)
without any ComfyUI framework dependency. See birefnet_model.py's header for
what was changed and why.
"""

import argparse
import json
import os
import types

import numpy as np
import torch
import torch.nn as nn
import torch.nn.functional as F
from PIL import Image
from safetensors.torch import load_file

from birefnet_model import BiRefNet

CONFIG = {
    "model_type": "birefnet",
    "image_mean": [0.0, 0.0, 0.0],
    "image_std": [1.0, 1.0, 1.0],
    "image_size": 1024,
}

_OPERATIONS = types.SimpleNamespace(
    Linear=nn.Linear, Conv2d=nn.Conv2d, BatchNorm2d=nn.BatchNorm2d, LayerNorm=nn.LayerNorm,
)

_model = None


def get_model():
    """Lazily load and cache the model (import-time is too early — the
    weights path is only known once the app starts)."""
    global _model
    if _model is None:
        weights_path = os.environ.get(
            "BIREFNET_WEIGHTS", "/opt/ComfyUI/models/background_removal/birefnet.safetensors"
        )
        sd = load_file(weights_path)
        model = BiRefNet(CONFIG, dtype=torch.float32, device=torch.device("cpu"), operations=_OPERATIONS)
        model.eval()
        missing, unexpected = model.load_state_dict(sd, strict=False)
        if missing or unexpected:
            raise RuntimeError(
                f"birefnet state dict mismatch: {len(missing)} missing, {len(unexpected)} unexpected keys"
            )
        _model = model
    return _model


def _preprocess(image: Image.Image, size: int, mean: list[float], std: list[float]) -> torch.Tensor:
    """Mirrors comfy/clip_model.py's clip_preprocess(..., crop=False)."""
    arr = np.array(image).astype(np.float32) / 255.0  # HWC, 0-1
    t = torch.from_numpy(arr).permute(2, 0, 1).unsqueeze(0)  # 1,3,H,W
    t = F.interpolate(t, size=(size, size), mode="bicubic", antialias=True)
    t = torch.clip(255.0 * t, 0, 255).round() / 255.0
    mean_t = torch.tensor(mean).view(3, 1, 1)
    std_t = torch.tensor(std).view(3, 1, 1)
    return (t - mean_t) / std_t


def remove_background(input_path: str, output_path: str) -> dict:
    """Run birefnet on input_path, write an RGBA PNG (original RGB + computed
    alpha) to output_path. Returns a small stats dict for logging/debugging."""
    model = get_model()
    image = Image.open(input_path).convert("RGB")
    W, H = image.size

    pixel_values = _preprocess(image, CONFIG["image_size"], CONFIG["image_mean"], CONFIG["image_std"])

    with torch.no_grad():
        out = model(pixel_values=pixel_values)
        out = F.interpolate(out, size=(H, W), mode="bicubic", antialias=False)
        mask = out.sigmoid().squeeze(0).squeeze(0)  # H, W

    mask_np = (mask.clamp(0, 1).numpy() * 255).astype(np.uint8)
    rgba = np.dstack([np.array(image), mask_np])

    os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
    Image.fromarray(rgba, mode="RGBA").save(output_path)

    return {
        "width": W,
        "height": H,
        "mask_mean": round(float(mask_np.mean()), 2),
        "mask_min": int(mask_np.min()),
        "mask_max": int(mask_np.max()),
    }


if __name__ == "__main__":
    # CLI entrypoint used by preprocess_service.py's native-dev fallback
    # (no bg-remover container; run this file as a subprocess instead).
    p = argparse.ArgumentParser()
    p.add_argument("--input", required=True)
    p.add_argument("--output", required=True)
    args = p.parse_args()
    result = remove_background(args.input, args.output)
    print("RESULT_JSON:" + json.dumps(result))
