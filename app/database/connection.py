import os
from pathlib import Path
import mysql.connector
from dotenv import load_dotenv

backend_dir = Path(__file__).resolve().parents[2]
load_dotenv(backend_dir / ".env", override=False)

def get_db_connection():
    port_val = os.getenv("DB_PORT", "3306")
    try:
        port = int(port_val) if port_val else 3306
    except (ValueError, TypeError):
        port = 3306

    return mysql.connector.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=port,
        database=os.getenv("DB_NAME", "training_management"),
        user=os.getenv("DB_USER", "root"),
        password=os.getenv("DB_PASSWORD", "")
    )
