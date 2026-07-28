# Background removal service: birefnet on CPU, no GPU/CUDA needed.
FROM python:3.11-slim

ENV DEBIAN_FRONTEND=noninteractive \
    COMFY_INPUT_DIR=/opt/ComfyUI/input \
    COMFY_OUTPUT_DIR=/opt/ComfyUI/output \
    BIREFNET_WEIGHTS=/opt/ComfyUI/models/background_removal/birefnet.safetensors

WORKDIR /app

COPY bg_remover/requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir -r /app/requirements.txt \
    # CPU-only torch/torchvision wheels — no CUDA libs, much smaller than the default index.
    && pip install --no-cache-dir --index-url https://download.pytorch.org/whl/cpu torch torchvision

COPY bg_remover/birefnet_model.py bg_remover/inference.py bg_remover/app.py /app/

EXPOSE 8400
CMD ["uvicorn", "app:app", "--host", "0.0.0.0", "--port", "8400"]
