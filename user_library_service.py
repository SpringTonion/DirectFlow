"""
user_library_service.py
-----------------------
Dịch vụ lõi xử lý các tính năng thư viện cá nhân và quản trị hệ thống:
  - Thêm / Xóa video yêu thích (Favorites)
  - Tạo cấu trúc danh sách phát (Playlists)
  - Sắp xếp và trích xuất dữ liệu dựa trên Metadata cào từ URL
  - Các hàm bổ trợ cho Admin quản lý User công khai
"""

import sqlite3
from database_setup import get_connection

# ================================================================
# 1. CHỨC NĂNG DANH SÁCH YÊU THÍCH (FAVORITES)
# ================================================================

def add_to_favorites(user_id: int, asset_id: int) -> dict:
    """Thêm một video vào danh sách yêu thích của người dùng"""
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO favorites (user_id, asset_id) VALUES (?, ?)",
                (user_id, asset_id)
            )
            conn.commit()
        return {"success": True, "message": "Đã thêm vào danh sách yêu thích"}
    except sqlite3.IntegrityError:
        return {"success": False, "message": "Video này đã nằm trong danh sách yêu thích từ trước"}
    except Exception as e:
        return {"success": False, "message": f"Lỗi hệ thống: {e}"}

def remove_from_favorites(user_id: int, asset_id: int) -> dict:
    """Xóa video khỏi danh sách yêu thích"""
    with get_connection() as conn:
        res = conn.execute(
            "DELETE FROM favorites WHERE user_id = ? AND asset_id = ?",
            (user_id, asset_id)
        )
        conn.commit()
        if res.rowcount > 0:
            return {"success": True, "message": "Đã xóa khỏi danh sách yêu thích"}
        return {"success": False, "message": "Video chưa từng tồn tại trong danh sách yêu thích"}


# ================================================================
# 2. CHỨC NĂNG DANH SÁCH PHÁT (PLAYLISTS)
# ================================================================

def create_playlist(user_id: int, name: str, is_public: int = 0) -> dict:
    """Tạo một playlist mới phân tách quyền riêng tư"""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO playlists (user_id, name, is_public) VALUES (?, ?, ?)",
                (user_id, name, is_public)
            )
            conn.commit()
            return {"success": True, "playlist_id": cursor.lastrowid, "message": "Tạo playlist thành công"}
    except Exception as e:
        return {"success": False, "message": f"Không thể tạo danh sách phát: {e}"}

def add_to_playlist(playlist_id: int, asset_id: int) -> dict:
    """Thêm video vào một playlist cụ thể"""
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO playlist_items (playlist_id, asset_id) VALUES (?, ?)",
                (playlist_id, asset_id)
            )
            conn.commit()
        return {"success": True, "message": "Đã thêm vào danh sách phát"}
    except sqlite3.IntegrityError:
        return {"success": False, "message": "Video này đã có sẵn trong danh sách phát này"}
    except Exception as e:
        return {"success": False, "message": str(e)}


# ================================================================
# 3. TRUY XUẤT + SẮP XẾP DANH SÁCH THEO METADATA (SORTING ENGINE)
# ================================================================

def get_user_saved_media(user_id: int, sort_by: str = "date_saved", order: str = "DESC") -> list:
    """
    Lấy toàn bộ danh sách các video một người dùng đã tải/lưu, hỗ trợ sắp xếp theo Metadata từ URL.
    """
    # Khớp cấu trúc từ điển bảo mật chống SQL Injection
    allowed_sort_fields = {
        "date_saved": "ud.downloaded_at",
        "views": "ma.view_count",
        "duration": "ma.duration_seconds",
        "date_published": "ma.published_at",
        "title": "ma.title"
    }
    
    sort_column = allowed_sort_fields.get(sort_by, "ud.downloaded_at")
    direction = "DESC" if order.upper() == "DESC" else "ASC"

    sql = f"""
        SELECT 
            ud.id AS download_id,
            ud.format_selected,
            ud.download_status,
            ud.downloaded_at,
            ma.id AS asset_id,
            ma.title,
            ma.platform,
            ma.source_url,
            ma.view_count,
            ma.duration_seconds,
            ma.published_at,
            c.channel_name AS author_name
        FROM user_downloads ud
        JOIN media_assets ma ON ud.asset_id = ma.id
        LEFT JOIN creators c ON ma.creator_id = c.id
        WHERE ud.user_id = ?
        ORDER BY {sort_column} {direction}
    """
    
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (user_id,))
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"❌ Lỗi Sorting Engine: {e}")
        return []


# ================================================================
# 4. CHỨC NĂNG QUẢN TRỊ USER (ADMIN DASHBOARD SERVICES)
# ================================================================

def get_all_users_admin(page: int = 1, per_page: int = 20, sort_by: str = 'created_at', order: str = 'DESC') -> dict:
    """Lấy danh sách phân trang và sắp xếp toàn bộ người dùng hệ thống cho Admin"""
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
    """Chỉnh sửa trạng thái hoạt động (Khóa/Mở) và Phân vai trò của User"""
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
    """Xóa sổ vĩnh viễn tài khoản người dùng khỏi cơ sở dữ liệu"""
    with get_connection() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (user_id,))
        conn.commit()
    return {'success': True, 'message': 'Đã xóa bỏ người dùng thành công.'}