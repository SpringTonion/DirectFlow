"""
auth_service.py
---------------
Xử lý toàn bộ logic nghiệp vụ liên quan đến xác thực:
  - Đăng ký tài khoản
  - Đăng nhập / Đăng xuất
  - Đổi mật khẩu
  - Lấy thông tin user
  - Vô hiệu hóa / Kích hoạt tài khoản (admin)
  (JWT token được xử lý bởi flask-jwt-extended trong app.py)
"""

import hashlib
import re
from datetime import datetime
import os
from werkzeug.security import generate_password_hash, check_password_hash
from database_setup import get_connection

_LEGACY_SALT = "directflow_salt_2024"


def _hash_password(password: str) -> str:
    """Hash mật khẩu bằng werkzeug (PBKDF2 + salt riêng cho mỗi user)."""
    return generate_password_hash(password)


def _legacy_hash_password(password: str) -> str:
    """Hash kiểu cũ (SHA256 + salt cố định) — chỉ dùng để verify tài khoản tạo trước migration."""
    return hashlib.sha256(f"{_LEGACY_SALT}{password}".encode()).hexdigest()


def _is_legacy_hash(stored_hash: str) -> bool:
    """Hash werkzeug có dạng 'method$salt$hash' (chứa dấu '$'); SHA256 cũ là hex 64 ký tự, không có '$'."""
    return '$' not in stored_hash


def _verify_password(stored_hash: str, password: str) -> bool:
    """Kiểm tra mật khẩu, hỗ trợ cả hash cũ (SHA256) và hash mới (werkzeug)."""
    if _is_legacy_hash(stored_hash):
        return stored_hash == _legacy_hash_password(password)
    return check_password_hash(stored_hash, password)

def _validate_email(email: str) -> bool:
    pattern = r'^[\w\.-]+@[\w\.-]+\.\w{2,}$'
    return bool(re.match(pattern, email))

def _validate_password(password: str) -> tuple[bool, str]:
    if len(password) < 6:
        return False, "Mật khẩu phải có ít nhất 6 ký tự."
    return True, ""

def _validate_username(username: str) -> tuple[bool, str]:
    if len(username) < 3:
        return False, "Tên đăng nhập phải có ít nhất 3 ký tự."
    if not re.match(r'^[a-zA-Z0-9_]+$', username):
        return False, "Tên đăng nhập chỉ được chứa chữ cái, số và dấu _."
    return True, ""

# ───── ĐĂNG KÝ ─────
def register_user(username: str, password: str, email: str = None, role: str = 'member') -> dict:
    ok, msg = _validate_username(username)
    if not ok:
        return {'success': False, 'message': msg, 'user_id': None}

    ok, msg = _validate_password(password)
    if not ok:
        return {'success': False, 'message': msg, 'user_id': None}

    if email and not _validate_email(email):
        return {'success': False, 'message': 'Email không hợp lệ.', 'user_id': None}

    if role not in ('guest', 'member', 'admin'):
        role = 'member'

    password_hash = _hash_password(password)

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO users (username, password_hash, email, role) VALUES (?, ?, ?, ?)",
                (username.strip(), password_hash, email, role)
            )
            conn.commit()
            user_id = cursor.lastrowid
        return {'success': True, 'message': 'Đăng ký thành công!', 'user_id': user_id}
    except Exception as e:
        if 'UNIQUE' in str(e):
            if 'username' in str(e):
                return {'success': False, 'message': 'Tên đăng nhập đã tồn tại.', 'user_id': None}
            if 'email' in str(e):
                return {'success': False, 'message': 'Email đã được sử dụng.', 'user_id': None}
        return {'success': False, 'message': f'Lỗi hệ thống: {e}', 'user_id': None}

# ───── ĐĂNG NHẬP ─────
# ĐÃ SỬA: nhận identifier (có thể là email hoặc username)
def login_user(identifier: str, password: str, ip_address: str = None) -> dict:
    if not identifier or not password:
        return {'success': False, 'message': 'Vui lòng nhập đầy đủ thông tin.', 'user': None}

    with get_connection() as conn:
        cursor = conn.cursor()
        # Tìm theo username hoặc email
        cursor.execute(
            "SELECT id, username, email, role, is_active, password_hash FROM users WHERE username = ? OR email = ?",
            (identifier.strip(), identifier.strip())
        )
        row = cursor.fetchone()

        if not row:
            return {'success': False, 'message': 'Sai tên đăng nhập hoặc mật khẩu.', 'user': None}

        # Kiểm tra mật khẩu (hỗ trợ cả hash cũ và hash mới)
        if not _verify_password(row['password_hash'], password):
            return {'success': False, 'message': 'Sai tên đăng nhập hoặc mật khẩu.', 'user': None}

        if not row['is_active']:
            return {'success': False, 'message': 'Tài khoản đã bị vô hiệu hóa.', 'user': None}

        # Nếu đang dùng hash cũ (SHA256), tự động nâng cấp lên werkzeug ngay khi login thành công
        if _is_legacy_hash(row['password_hash']):
            cursor.execute(
                "UPDATE users SET password_hash = ? WHERE id = ?",
                (_hash_password(password), row['id'])
            )

        # Cập nhật last_login_at
        now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
        cursor.execute("UPDATE users SET last_login_at = ? WHERE id = ?", (now, row['id']))

        # Ghi log
        cursor.execute(
            "INSERT INTO system_logs (user_id, action_type, ip_address, details) VALUES (?, 'LOGIN', ?, ?)",
            (row['id'], ip_address, f"User '{row['username']}' đăng nhập thành công.")
        )
        conn.commit()

    user_data = {
        'id': row['id'],
        'username': row['username'],
        'email': row['email'],
        'role': row['role']
    }
    # Token được tạo bởi flask-jwt-extended trong app.py
    return {
        'success': True,
        'message': 'Đăng nhập thành công!',
        'user': user_data,
    }

# ───── ĐĂNG XUẤT ─────
def logout_user(user_id: int, ip_address: str = None) -> dict:
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO system_logs (user_id, action_type, ip_address, details) VALUES (?, 'LOGOUT', ?, ?)",
                (user_id, ip_address, f"User ID {user_id} đăng xuất.")
            )
            conn.commit()
        return {'success': True, 'message': 'Đăng xuất thành công.'}
    except Exception as e:
        return {'success': False, 'message': str(e)}

# ───── ĐỔI MẬT KHẨU ─────
def change_password(user_id: int, old_password: str, new_password: str) -> dict:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT password_hash FROM users WHERE id = ?", (user_id,))
        row = cursor.fetchone()
        if not row or not _verify_password(row['password_hash'], old_password):
            return {'success': False, 'message': 'Mật khẩu cũ không đúng.'}

        ok, msg = _validate_password(new_password)
        if not ok:
            return {'success': False, 'message': msg}

        new_hash = _hash_password(new_password)
        cursor.execute("UPDATE users SET password_hash = ? WHERE id = ?", (new_hash, user_id))
        conn.commit()

    return {'success': True, 'message': 'Đổi mật khẩu thành công.'}

# ───── LẤY THÔNG TIN USER ─────
def get_user_by_id(user_id: int) -> dict | None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id, username, email, role, is_active, last_login_at, created_at FROM users WHERE id = ?",
            (user_id,)
        )
        row = cursor.fetchone()
    return dict(row) if row else None

def get_all_users(page: int = 1, per_page: int = 20) -> dict:
    offset = (page - 1) * per_page
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total = cursor.fetchone()[0]

        cursor.execute(
            "SELECT id, username, email, role, is_active, last_login_at, created_at FROM users ORDER BY id DESC LIMIT ? OFFSET ?",
            (per_page, offset)
        )
        rows = [dict(r) for r in cursor.fetchall()]

    return {'total': total, 'page': page, 'per_page': per_page, 'users': rows}

# ───── ADMIN: KÍCH HOẠT / VÔ HIỆU HÓA ─────
def set_user_active(user_id: int, is_active: bool) -> dict:
    with get_connection() as conn:
        conn.execute("UPDATE users SET is_active = ? WHERE id = ?", (int(is_active), user_id))
        conn.commit()
    status = 'kích hoạt' if is_active else 'vô hiệu hóa'
    return {'success': True, 'message': f'Tài khoản đã được {status}.'}

def update_user_role(user_id: int, new_role: str) -> dict:
    if new_role not in ('guest', 'member', 'admin'):
        return {'success': False, 'message': 'Role không hợp lệ.'}
    with get_connection() as conn:
        conn.execute("UPDATE users SET role = ? WHERE id = ?", (new_role, user_id))
        conn.commit()
    return {'success': True, 'message': f'Đã cập nhật role thành {new_role}.'}

# ================================================================
# CHỨC NĂNG DÀNH RIÊNG CHO QUẢN TRỊ VIÊN (ADMIN ONLY)
# ================================================================

def get_all_users_admin(page: int = 1, per_page: int = 20, sort_by: str = 'created_at', order: str = 'DESC') -> dict:
    """Lấy danh sách người dùng, hỗ trợ Sort theo ID, Tên, Ngày tham gia, Đăng nhập cuối"""
    allowed_sort = {
        'id': 'id', 
        'username': 'username', 
        'created_at': 'created_at', 
        'last_login_at': 'last_login_at'
    }
    sort_col = allowed_sort.get(sort_by, 'created_at')
    direction = "ASC" if order.upper() == "ASC" else "DESC"
    offset = (page - 1) * per_page
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        total = cursor.fetchone()[0]
        
        cursor.execute(f"""
            SELECT id, username, email, role, is_active, last_login_at, created_at 
            FROM users 
            ORDER BY {sort_col} {direction} 
            LIMIT ? OFFSET ?
        """, (per_page, offset))
        rows = [dict(r) for r in cursor.fetchall()]
        
    return {'total': total, 'page': page, 'per_page': per_page, 'users': rows}

def modify_user_admin(user_id: int, is_active: int, role: str) -> dict:
    """Modify: Chỉnh sửa trạng thái (Khóa/Mở) và Chức vụ của người dùng"""
    if role not in ('member', 'admin'): 
        role = 'member'
    with get_connection() as conn:
        conn.execute(
            "UPDATE users SET is_active = ?, role = ? WHERE id = ?", 
            (is_active, role, user_id)
        )
        conn.commit()
    return {'success': True, 'message': 'Đã cập nhật thông tin người dùng.'}

def delete_user_admin(user_id: int) -> dict:
    """Xóa sổ hoàn toàn người dùng khỏi hệ thống"""
    # Nhờ ON DELETE CASCADE trong database_setup.py, 
    # khi xóa User, toàn bộ lịch sử tải, playlist của người này sẽ tự động bay màu sạch sẽ!
    with get_connection() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    return {'success': True, 'message': 'Đã xóa bỏ người dùng và toàn bộ dữ liệu rác của họ.'}