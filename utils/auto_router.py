"""
Auto Router
-----------
Routes a classified civic report automatically to the correct
municipal department based on category, and generates a unique
tracking ID for the citizen.
"""

import random
import string
from datetime import datetime
from config import Config


def route_to_department(category):
    return Config.DEPARTMENTS.get(category, Config.DEPARTMENTS['other'])


def generate_tracking_id():
    date_part = datetime.now().strftime('%y%m%d')
    rand_part = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
    return f"CIV-{date_part}-{rand_part}"