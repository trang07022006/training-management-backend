import uuid
from werkzeug.security import generate_password_hash
from app.database.connection import get_db_connection

def setup_scrum127_data():
    conn = get_db_connection()
    cur = conn.cursor(dictionary=True)

    # 1. Update trang test to training_manager in users table
    cur.execute("""
        UPDATE users SET role = 'training_manager' 
        WHERE email = 'trang111@gmail.com'
    """)

    # 2. Ensure QA Consultant 02 exists
    cur.execute("SELECT id FROM users WHERE email = 'qa.consultant02@ictu.test'")
    row = cur.fetchone()
    if not row:
        consultant_b_id = str(uuid.uuid4())
        pw_hash = generate_password_hash('Password@123')
        cur.execute("""
            INSERT INTO users (id, email, name, password_hash, role, status, created_at, updated_at)
            VALUES (%s, %s, %s, %s, %s, %s, NOW(), NOW())
        """, (consultant_b_id, 'qa.consultant02@ictu.test', 'QA Consultant 02', pw_hash, 'consultant', 'active'))
    else:
        consultant_b_id = row['id']
        cur.execute("UPDATE users SET name = 'QA Consultant 02', role = 'consultant', status = 'active' WHERE id = %s", (consultant_b_id,))

    # Ensure QA Consultant 02 has role-id-consultant in user_roles
    cur.execute("SELECT 1 FROM user_roles WHERE user_id = %s AND role_id = 'role-id-consultant'", (consultant_b_id,))
    if not cur.fetchone():
        cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-consultant', NOW())", (consultant_b_id,))

    # 3. Ensure test (Consultant A) has role consultant
    cur.execute("SELECT id FROM users WHERE email = '070206@gmail.com'")
    row_a = cur.fetchone()
    if row_a:
        consultant_a_id = row_a['id']
        cur.execute("UPDATE users SET name = 'test', role = 'consultant', status = 'active' WHERE id = %s", (consultant_a_id,))
        cur.execute("SELECT 1 FROM user_roles WHERE user_id = %s AND role_id = 'role-id-consultant'", (consultant_a_id,))
        if not cur.fetchone():
            cur.execute("INSERT INTO user_roles (user_id, role_id, created_at) VALUES (%s, 'role-id-consultant', NOW())", (consultant_a_id,))

    # 4. Prepare leads QA-S127-A, QA-S127-B, QA-S127-C
    leads_data = [
        ('QA-S127-A', '0912700001', 'qa.s127a@ictu.test'),
        ('QA-S127-B', '0912700002', 'qa.s127b@ictu.test'),
        ('QA-S127-C', '0912700003', 'qa.s127c@ictu.test'),
    ]

    for name, phone, email in leads_data:
        cur.execute("SELECT id FROM leads WHERE full_name = %s", (name,))
        l_row = cur.fetchone()
        if not l_row:
            lid = str(uuid.uuid4())
            cur.execute("""
                INSERT INTO leads (id, full_name, phone, email, source, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'direct', 'new', NOW(), NOW())
            """, (lid, name, phone, email))
        else:
            cur.execute("UPDATE leads SET assigned_to_user_id = NULL, assigned_at = NULL WHERE id = %s", (l_row['id'],))

    conn.commit()
    print("Test data for SCRUM-127 prepared successfully.")
    cur.close()
    conn.close()

if __name__ == '__main__':
    setup_scrum127_data()
