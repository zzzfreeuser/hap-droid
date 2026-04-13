import os
import mimetypes
import base64

def image_to_data_url(image_path):
    if not os.path.isfile(image_path):
        raise FileNotFoundError(f"Image file not found: {image_path}")

    with open(image_path, "rb") as f:
        image_data = f.read()

    mime_type, _ = mimetypes.guess_type(image_path)

    if mime_type is None or not mime_type.startswith('image/'):
        mime_type = 'image/png'

    base64_encoded = base64.b64encode(image_data).decode('utf-8')
    return f"data:{mime_type};base64,{base64_encoded}"

print(image_to_data_url("D:\\GithubProjects\\hap-droid\\out\\shui_llm_converted\\2026-04-13-17-38-05\\temp\\screenCap_201340601677.png"))