import unittest
import threading
from unittest.mock import MagicMock, patch
from flask import Flask
from mysql.connector.errors import PoolError

from app.database import connection
from app.services.authorization_service import get_user_permissions, has_permission


class ConnectionPoolTests(unittest.TestCase):
    def setUp(self):
        connection.reset_db_pool()

    def tearDown(self):
        connection.reset_db_pool()

    def test_get_db_connection_returns_pooled_connection(self):
        """get_db_connection lấy kết nối từ pool và khi close được trả lại cho pool."""
        conn = connection.get_db_connection()
        self.assertIsNotNone(conn)
        self.assertTrue(conn.is_connected())
        # Đóng kết nối -> trả về pool
        conn.close()

    def test_concurrent_connections_isolated(self):
        """Các kết nối đồng thời từ các thread khác nhau không chia sẻ connection hay cursor."""
        results = []
        errors = []

        def worker(idx):
            try:
                conn = connection.get_db_connection()
                cursor = conn.cursor(dictionary=True)
                cursor.execute("SELECT %s as val", (idx,))
                row = cursor.fetchone()
                results.append((idx, row["val"]))
                cursor.close()
                conn.close()
            except Exception as e:
                errors.append(e)

        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        self.assertEqual(len(errors), 0)
        self.assertEqual(len(results), 5)
        for idx, val in results:
            self.assertEqual(idx, val)

    def test_pool_exhaustion_fallback(self):
        """Khi pool gặp PoolError, get_db_connection có fallback an toàn mở kết nối trực tiếp."""
        mock_pool = MagicMock()
        mock_pool.get_connection.side_effect = PoolError("Queue full")
        
        with patch("app.database.connection.get_connection_pool", return_value=mock_pool):
            with patch("app.database.connection.mysql.connector.connect") as mock_direct_connect:
                mock_conn = MagicMock()
                mock_direct_connect.return_value = mock_conn
                
                conn = connection.get_db_connection()
                self.assertEqual(conn, mock_conn)
                mock_direct_connect.assert_called_once()


class PerRequestAuthorizationCacheTests(unittest.TestCase):
    def setUp(self):
        self.app = Flask("test_auth_app")

    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_permissions_cached_within_single_request(self, mock_rp_codes, mock_ur_roles):
        """Trong cùng một request context, permissions chỉ query database một lần."""
        mock_role = MagicMock()
        mock_role.id = 1
        mock_ur_roles.return_value = [mock_role]
        mock_rp_codes.return_value = ["user.view", "user.manage"]

        with self.app.test_request_context():
            # Lần gọi 1
            perms1 = get_user_permissions("u123")
            # Lần gọi 2 trong cùng request
            perms2 = get_user_permissions("u123")

            self.assertEqual(perms1, ["user.manage", "user.view"])
            self.assertEqual(perms2, ["user.manage", "user.view"])
            # Database chỉ được truy vấn 1 lần duy nhất
            self.assertEqual(mock_ur_roles.call_count, 1)
            self.assertEqual(mock_rp_codes.call_count, 1)

    @patch("app.services.authorization_service.user_role_repository.get_roles_by_user_id")
    @patch("app.services.authorization_service.role_permission_repository.get_permission_codes_by_role_id")
    def test_permissions_not_shared_across_different_requests(self, mock_rp_codes, mock_ur_roles):
        """Giữa hai request khác nhau, quyền không bị cache rò rỉ mà được truy vấn tươi mới."""
        mock_role = MagicMock()
        mock_role.id = 1
        mock_ur_roles.return_value = [mock_role]
        mock_rp_codes.return_value = ["user.view"]

        # Request 1
        with self.app.test_request_context():
            get_user_permissions("u123")
            self.assertEqual(mock_ur_roles.call_count, 1)

        # Request 2 (độc lập)
        with self.app.test_request_context():
            get_user_permissions("u123")
            # Phải được gọi thêm lần thứ 2
            self.assertEqual(mock_ur_roles.call_count, 2)
