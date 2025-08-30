# create_admin.py
from auth import get_conn, create_or_update_admin_from_env

if __name__ == "__main__":
    conn = get_conn()
    create_or_update_admin_from_env(conn)
    conn.close()
