import os
from werkzeug.utils import secure_filename
from PIL import Image
import uuid
from config import Config


def allowed_file(filename):
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in Config.ALLOWED_EXTENSIONS


def save_uploaded_image(file):
    if not file or not allowed_file(file.filename):
        return None

    ext = file.filename.rsplit('.', 1)[1].lower()
    unique_name = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(Config.UPLOAD_FOLDER, unique_name)

    os.makedirs(Config.UPLOAD_FOLDER, exist_ok=True)
    file.save(filepath)

    # Compress / normalize image size
    try:
        img = Image.open(filepath)
        img.thumbnail((800, 800))
        img.save(filepath, optimize=True, quality=80)
    except Exception as e:
        print(f"Image processing warning: {e}")

    return f"uploads/{unique_name}"