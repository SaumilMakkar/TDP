import os
from app import create_app

app = create_app()

if __name__ == '__main__':
    # Initialize DB if it doesn't exist
    DB_PATH = app.config.get('DB_PATH', 'database/doctor_decisions.db')
    if not os.path.exists(DB_PATH):
        print(f"Warning: Database {DB_PATH} not found. Please run setup_db.py first.")
    
    app.run(debug=True, port=5000)
