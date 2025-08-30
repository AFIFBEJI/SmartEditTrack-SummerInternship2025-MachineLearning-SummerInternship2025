# create_admin.py

from dotenv import load_dotenv
load_dotenv()

from auth import get_conn, create_or_update_admin_from_env
if __name__ == "__main__":
    conn = get_conn()
    create_or_update_admin_from_env(conn)
    conn.close()

from auth import get_conn, create_or_update_admin_from_env

if __name__ == "__main__":
    conn = get_conn()
    create_or_update_admin_from_env(conn)
    conn.close()
