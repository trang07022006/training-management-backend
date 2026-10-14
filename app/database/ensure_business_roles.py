import logging

from app.database.connection import get_db_connection

logger = logging.getLogger(__name__)


def ensure_business_roles() -> None:
    """Synchronize business roles and permissions after the SQL migrations run.

    Schema creation belongs to the ordered SQL migrations in ``database/scripts``.
    Keeping DDL out of this startup data synchronizer avoids creating tables with
    missing prerequisites (for example, lead history before ``leads`` exists).
    """
    connection = None
    try:
        connection = get_db_connection()
        with connection.cursor() as cursor:
            cursor.execute(
                """
                INSERT INTO roles (id, code, name, description, created_at, updated_at)
                VALUES
                    ('role-id-consultant', 'consultant', 'Tư vấn tuyển sinh',
                     'Tư vấn tuyển sinh và quản lý khách hàng tiềm năng', NOW(), NOW()),
                    ('role-id-training-manager', 'training_manager', 'Quản lý đào tạo',
                     'Quản lý chương trình đào tạo và khách hàng tiềm năng', NOW(), NOW())
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    description = VALUES(description),
                    updated_at = NOW()
                """
            )
            cursor.execute(
                """
                INSERT INTO permissions (id, code, name, description, created_at, updated_at)
                VALUES ('perm-id-lead-delete', 'lead.delete', 'Xóa khách hàng tiềm năng',
                        'Quyền xóa khách hàng tiềm năng trong hệ thống', NOW(), NOW())
                ON DUPLICATE KEY UPDATE
                    name = VALUES(name),
                    description = VALUES(description),
                    updated_at = NOW()
                """
            )
            cursor.execute(
                """
                INSERT IGNORE INTO role_permissions (role_id, permission_id, created_at)
                VALUES
                    ('role-id-training-manager', 'perm-id-course-view', NOW()),
                    ('role-id-training-manager', 'perm-id-course-manage', NOW()),
                    ('role-id-training-manager', 'perm-id-session-view', NOW()),
                    ('role-id-training-manager', 'perm-id-lead-delete', NOW()),
                    ('role-id-consultant', 'perm-id-course-view', NOW()),
                    ('role-id-consultant', 'perm-id-course-manage', NOW()),
                    ('role-id-consultant', 'perm-id-session-view', NOW()),
                    ('role-id-admin', 'perm-id-lead-delete', NOW())
                """
            )
        connection.commit()
        logger.info("Business roles and permissions synchronized successfully.")
    except Exception as error:
        if connection is not None:
            connection.rollback()
        logger.warning("Could not synchronize business roles and permissions: %s", error)
    finally:
        if connection is not None:
            connection.close()
