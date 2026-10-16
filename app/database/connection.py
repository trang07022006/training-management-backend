import os
from pathlib import Path
import threading
import mysql.connector
from mysql.connector import pooling
from mysql.connector.errors import PoolError
from dotenv import load_dotenv

backend_dir = Path(__file__).resolve().parents[2]
load_dotenv(backend_dir / ".env", override=False)

_pool_lock = threading.Lock()
_connection_pool = None


def _get_db_config():
    port_val = os.getenv("DB_PORT", "3306")
    try:
        port = int(port_val) if port_val else 3306
    except (ValueError, TypeError):
        port = 3306

    pool_size_val = os.getenv("DB_POOL_SIZE", "10")
    try:
        pool_size = max(1, min(int(pool_size_val), 32))
    except (ValueError, TypeError):
        pool_size = 10

    return {
        "host": os.getenv("DB_HOST", "localhost"),
        "port": port,
        "database": os.getenv("DB_NAME", "training_management"),
        "user": os.getenv("DB_USER", "root"),
        "password": os.getenv("DB_PASSWORD", ""),
        "pool_size": pool_size,
    }


def get_connection_pool():
    global _connection_pool
    if _connection_pool is None:
        with _pool_lock:
            if _connection_pool is None:
                config = _get_db_config()
                _connection_pool = pooling.MySQLConnectionPool(
                    pool_name="training_management_pool",
                    pool_size=config["pool_size"],
                    pool_reset_session=True,
                    host=config["host"],
                    port=config["port"],
                    database=config["database"],
                    user=config["user"],
                    password=config["password"],
                )
    return _connection_pool


def reset_db_pool():
    """Hỗ trợ dọn dẹp hoặc khởi tạo lại pool khi cần (ví dụ trong môi trường test)."""
    global _connection_pool
    with _pool_lock:
        _connection_pool = None


def get_db_connection():
    """
    Lấy kết nối MySQL từ connection pool của mysql-connector-python.
    - Kết nối trả về là pooled connection.
    - Khi caller gọi connection.close() trong khối finally, connection sẽ được hoàn trả về pool.
    - pool_reset_session=True đảm bảo reset trạng thái phiên và transaction khi trả về/lấy ra.
    - Xử lý PoolError rõ ràng nếu pool bị kiệt, an toàn đa luồng.
    """
    try:
        pool = get_connection_pool()
        return pool.get_connection()
    except PoolError:
        config = _get_db_config()
        return mysql.connector.connect(
            host=config["host"],
            port=config["port"],
            database=config["database"],
            user=config["user"],
            password=config["password"],
        )
