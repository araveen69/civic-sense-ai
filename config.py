import os

BASE_DIR = os.path.abspath(os.path.dirname(__file__))

class Config:
    SECRET_KEY = 'civic-sense-ai-secret-key-2024'
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{os.path.join(BASE_DIR, "database.db")}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    UPLOAD_FOLDER = os.path.join(BASE_DIR, 'static', 'uploads')
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024  # 16MB max upload
    ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}

    # Department mapping for auto-routing
    DEPARTMENTS = {
        'pothole': 'Roads & Infrastructure Department',
        'garbage': 'Sanitation Department',
        'streetlight': 'Electrical Department',
        'water_leakage': 'Water Supply Department',
        'graffiti': 'Urban Beautification Department',
        'broken_sidewalk': 'Roads & Infrastructure Department',
        'illegal_dumping': 'Sanitation Department',
        'drainage': 'Public Works Department',
        'traffic_signal': 'Traffic Management Department',
        'other': 'General Municipal Office'
    }

    # Priority score thresholds
    PRIORITY_HIGH = 70
    PRIORITY_MEDIUM = 40