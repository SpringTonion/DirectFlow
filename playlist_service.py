"""
playlist_service.py
-------------------
Quản lý playlist cá nhân của user:
  - Tạo / Sửa / Xóa playlist
  - Thêm / Xóa media khỏi playlist
  - Lấy danh sách playlist của cá nhân
"""

from database_setup import get_connection

def create_playlist(user_id: int, name: str, is_public: bool = False) -> dict:
    """Tạo thư mục playlist mới cho người dùng."""
    clean_user_id = int(user_id) # SỬA LỖI
    name = name.strip()
    if not name:
        return {'success': False, 'message': 'Tên playlist không được để trống.'}
    if len(name) > 100:
        return {'success': False, 'message': 'Tên playlist tối đa 100 ký tự.'}

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO playlists (user_id, name, is_public) VALUES (?, ?, ?)",
                (clean_user_id, name, int(is_public))
            )
            conn.commit()
            return {'success': True, 'message': 'Tạo playlist thành công.', 'playlist_id': cursor.lastrowid}
    except Exception as e:
        return {'success': False, 'message': str(e)}

def delete_playlist(playlist_id: int, user_id: int) -> dict:
    """Xóa hoàn toàn playlist (Tự động xóa các mục bên trong nhờ CASCADE)."""
    clean_user_id = int(user_id) # SỬA LỖI
    if not _is_owner(playlist_id, clean_user_id):
        return {'success': False, 'message': 'Bạn không có quyền quản lý playlist này.'}

    with get_connection() as conn:
        conn.execute("DELETE FROM playlists WHERE id = ?", (playlist_id,))
        conn.commit()
    return {'success': True, 'message': 'Đã xóa playlist.'}

def add_to_playlist(playlist_id: int, asset_id: int, user_id: int) -> dict:
    """Đẩy liên kết video vào một playlist cụ thể."""
    clean_user_id = int(user_id) # SỬA LỖI
    if not _is_owner(playlist_id, clean_user_id):
        return {'success': False, 'message': 'Bạn không có quyền chỉnh sửa playlist này.'}

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO playlist_items (playlist_id, asset_id) VALUES (?, ?)",
                (playlist_id, asset_id)
            )
            conn.commit()
            return {'success': True, 'message': 'Đã thêm video vào playlist thành công.'}
    except Exception as e:
        if 'UNIQUE' in str(e):
            return {'success': False, 'message': 'Video này đã tồn tại trong playlist.'}
        return {'success': False, 'message': str(e)}

def get_user_playlists(user_id: int) -> list:
    """Lấy toàn bộ danh sách danh mục playlist cá nhân để render lên UI."""
    clean_user_id = int(user_id) # SỬA LỖI
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT p.id, p.name, p.is_public, p.created_at
            FROM playlists p
            WHERE p.user_id = ?
            ORDER BY p.created_at DESC
        ''', (clean_user_id,))
        return [dict(r) for r in cursor.fetchall()]

def _is_owner(playlist_id: int, user_id: int) -> bool:
    """Kiểm tra quyền sở hữu bảo mật."""
    clean_user_id = int(user_id) # SỬA LỖI
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM playlists WHERE id = ? AND user_id = ?", (playlist_id, clean_user_id))
        return cursor.fetchone() is not None

def get_playlist_contents(playlist_id: int, user_id: int) -> dict:
    """Lấy danh sách chi tiết các video nằm bên trong một Playlist cụ thể."""
    if not _is_owner(playlist_id, user_id):
        return {'success': False, 'message': 'Bạn không có quyền xem nội dung thư mục phát này.'}

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT 
                ma.id AS asset_id, ma.title, ma.platform, ma.source_url,
                ma.duration_seconds, ma.view_count, mc.thumbnail_url
            FROM playlist_items pi
            JOIN media_assets ma ON pi.asset_id = ma.id
            LEFT JOIN media_cache mc ON ma.id = mc.asset_id
            WHERE pi.playlist_id = ?
            GROUP BY ma.id
        ''', (playlist_id,))
        rows = [dict(r) for r in cursor.fetchall()]
        
    return {'success': True, 'items': rows}