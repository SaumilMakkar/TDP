import os

class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY', 'super-secret-key-change-this-to-a-long-random-value')
    BASE_DIR = os.path.dirname(os.path.abspath(__file__))
    DB_PATH = os.path.join(BASE_DIR, 'database', 'doctor_decisions.db')
    AUTO_APPROVE_THRESHOLD = 0.9  # AI confidence >= this value → auto-approved, skips doctor review
