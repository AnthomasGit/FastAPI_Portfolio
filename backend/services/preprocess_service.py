import os
import uuid
from rembg import remove as rembg_remove


def remove_background(input_path: str, output_dir: str) -> str:
    output_filename = f"{uuid.uuid4()}.png"
    output_path = os.path.join(output_dir, output_filename)
    with open(input_path, "rb") as f:
        input_data = f.read()
    output_data = rembg_remove(input_data)
    with open(output_path, "wb") as f:
        f.write(output_data)
    return output_filename
