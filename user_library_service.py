"""
user_library_service.py
-----------------------
Dịch vụ lõi xử lý toàn bộ tính năng thư viện cá nhân của người dùng:
  - Yêu thích (Favorites) — dùng bảng `favorites` riêng (composite key user_id + asset_id)
  - Danh sách phát (Playlists) — tạo / xóa / thêm video / xem nội dung (chỉ riêng tư, không hỗ trợ public)
  - Kho lưu trữ cá nhân (Saved Media) — truy xuất + sắp xếp theo metadata

Toàn bộ dữ liệu đọc/viết đều đi qua đây để tránh trùng lặp logic SQL ở app.py.
"""

import sqlite3
from database_setup import get_connection

# ================================================================
# 1. CHỨC NĂNG DANH SÁCH YÊU THÍCH (FAVORITES)
# ================================================================

def add_to_favorites(user_id: int, asset_id: int) -> dict:
    """Thêm một video vào danh sách yêu thích của người dùng."""
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT INTO favorites (user_id, asset_id) VALUES (?, ?)",
                (int(user_id), int(asset_id))
            )
            conn.commit()
        return {"success": True, "message": "Đã thêm vào danh sách yêu thích"}
    except sqlite3.IntegrityError:
        return {"success": False, "message": "Video này đã nằm trong danh sách yêu thích từ trước"}
    except Exception as e:
        return {"success": False, "message": f"Lỗi hệ thống: {e}"}


def remove_from_favorites(user_id: int, asset_id: int) -> dict:
    """Xóa video khỏi danh sách yêu thích."""
    with get_connection() as conn:
        res = conn.execute(
            "DELETE FROM favorites WHERE user_id = ? AND asset_id = ?",
            (int(user_id), int(asset_id))
        )
        conn.commit()
        if res.rowcount > 0:
            return {"success": True, "message": "Đã xóa khỏi danh sách yêu thích"}
        return {"success": False, "message": "Video chưa từng tồn tại trong danh sách yêu thích"}


def toggle_favorite(user_id: int, asset_id: int) -> dict:
    """Bật/tắt yêu thích trong 1 lệnh gọi — tiện cho nút toggle trên UI."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND asset_id = ?",
            (int(user_id), int(asset_id))
        )
        if cursor.fetchone():
            conn.execute(
                "DELETE FROM favorites WHERE user_id = ? AND asset_id = ?",
                (int(user_id), int(asset_id))
            )
            conn.commit()
            return {"success": True, "action": "removed", "message": "Đã bỏ yêu thích"}

        conn.execute(
            "INSERT INTO favorites (user_id, asset_id) VALUES (?, ?)",
            (int(user_id), int(asset_id))
        )
        conn.commit()
        return {"success": True, "action": "added", "message": "Đã thêm vào yêu thích"}


def get_user_favorites(user_id: int) -> list:
    """Lấy danh sách video yêu thích kèm metadata + thumbnail để render UI."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT
                ma.id AS asset_id, ma.title, ma.platform, ma.source_url,
                ma.duration_seconds, ma.view_count, f.added_at,
                MAX(mc.thumbnail_url) AS thumbnail_url
            FROM favorites f
            JOIN media_assets ma ON f.asset_id = ma.id
            LEFT JOIN media_cache mc ON ma.id = mc.asset_id
            WHERE f.user_id = ?
            GROUP BY ma.id
            ORDER BY f.added_at DESC
        ''', (int(user_id),))
        return [dict(r) for r in cursor.fetchall()]


def is_favorite(user_id: int, asset_id: int) -> bool:
    """Kiểm tra nhanh 1 asset có đang được yêu thích hay không."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM favorites WHERE user_id = ? AND asset_id = ?",
            (int(user_id), int(asset_id))
        )
        return cursor.fetchone() is not None


# ================================================================
# 2. CHỨC NĂNG DANH SÁCH PHÁT (PLAYLISTS) — CHỈ RIÊNG TƯ
# ================================================================

def _is_owner(playlist_id: int, user_id: int) -> bool:
    """Kiểm tra quyền sở hữu playlist (bảo mật)."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM playlists WHERE id = ? AND user_id = ?",
            (int(playlist_id), int(user_id))
        )
        return cursor.fetchone() is not None


def create_playlist(user_id: int, name: str) -> dict:
    """Tạo playlist mới cho người dùng. Playlist luôn riêng tư (is_public = 0)."""
    clean_user_id = int(user_id)
    name = (name or "").strip()
    if not name:
        return {"success": False, "message": "Tên playlist không được để trống."}
    if len(name) > 100:
        return {"success": False, "message": "Tên playlist tối đa 100 ký tự."}

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO playlists (user_id, name, is_public) VALUES (?, ?, 0)",
                (clean_user_id, name)
            )
            conn.commit()
            return {"success": True, "playlist_id": cursor.lastrowid, "message": "Tạo playlist thành công."}
    except Exception as e:
        return {"success": False, "message": str(e)}


def delete_playlist(playlist_id: int, user_id: int) -> dict:
    """Xóa hoàn toàn playlist (tự động xóa các mục bên trong nhờ CASCADE)."""
    clean_user_id = int(user_id)
    if not _is_owner(playlist_id, clean_user_id):
        return {"success": False, "message": "Bạn không có quyền quản lý playlist này."}

    with get_connection() as conn:
        conn.execute("DELETE FROM playlists WHERE id = ?", (int(playlist_id),))
        conn.commit()
    return {"success": True, "message": "Đã xóa playlist."}


def add_to_playlist(playlist_id: int, asset_id: int, user_id: int) -> dict:
    """Đẩy/Rút video khỏi playlist (toggle), chỉ khi đúng chủ sở hữu."""
    clean_user_id = int(user_id)

    if int(playlist_id) == FAVORITES_VIRTUAL_PLAYLIST_ID:
        result = toggle_favorite(clean_user_id, asset_id)
        result["message"] = "Đã thêm vào yêu thích." if result["action"] == "added" else "Đã xóa khỏi yêu thích."
        return result

    if not _is_owner(playlist_id, clean_user_id):
        return {"success": False, "message": "Bạn không có quyền chỉnh sửa playlist này."}

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT asset_id FROM playlist_items WHERE playlist_id = ? AND asset_id = ?",
                (int(playlist_id), int(asset_id))
            )
            if cursor.fetchone():
                conn.execute(
                    "DELETE FROM playlist_items WHERE playlist_id = ? AND asset_id = ?",
                    (int(playlist_id), int(asset_id))
                )
                conn.commit()
                return {"success": True, "action": "removed", "message": "Đã xóa khỏi danh sách phát."}

            conn.execute(
                "INSERT INTO playlist_items (playlist_id, asset_id) VALUES (?, ?)",
                (int(playlist_id), int(asset_id))
            )
            conn.commit()
            return {"success": True, "action": "added", "message": "Đã thêm vào danh sách phát."}
    except Exception as e:
        return {"success": False, "message": str(e)}


FAVORITES_VIRTUAL_PLAYLIST_ID = -1  # playlist ảo, không lưu trong bảng `playlists`


def get_user_playlists(user_id: int) -> list:
    """Lấy toàn bộ danh mục playlist cá nhân để render lên UI.
    Luôn chèn thêm 1 playlist ảo 'Favorite' ở đầu danh sách, đại diện cho bảng `favorites`.
    """
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id, name, created_at
            FROM playlists
            WHERE user_id = ?
            ORDER BY created_at DESC
        ''', (int(user_id),))
        playlists = [dict(r) for r in cursor.fetchall()]

    favorite_entry = {"id": FAVORITES_VIRTUAL_PLAYLIST_ID, "name": "Favorite", "created_at": None}
    return [favorite_entry] + playlists


def get_playlist_contents(playlist_id: int, user_id: int) -> dict:
    """Lấy danh sách chi tiết các video nằm bên trong một playlist cụ thể."""
    if int(playlist_id) == FAVORITES_VIRTUAL_PLAYLIST_ID:
        return {"success": True, "items": get_user_favorites(user_id)}

    if not _is_owner(playlist_id, user_id):
        return {"success": False, "message": "Bạn không có quyền xem nội dung danh sách phát này."}

    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT
                ma.id AS asset_id, ma.title, ma.platform, ma.source_url,
                ma.duration_seconds, ma.view_count,
                MAX(mc.thumbnail_url) AS thumbnail_url
            FROM playlist_items pi
            JOIN media_assets ma ON pi.asset_id = ma.id
            LEFT JOIN media_cache mc ON ma.id = mc.asset_id
            WHERE pi.playlist_id = ?
            GROUP BY ma.id
        ''', (int(playlist_id),))
        rows = [dict(r) for r in cursor.fetchall()]

    return {"success": True, "items": rows}


def record_download(user_id: int, asset_id: int, quality: str) -> dict:
    """Ghi nhận 1 lượt tải vào kho cá nhân, chống dupe theo TỪNG ASSET (không tính quality).
    Nếu user đã có asset này trong kho (bất kể trước đó chọn chất lượng nào) -> chỉ cập nhật
    chất lượng + thời gian tải gần nhất của dòng cũ, KHÔNG insert thêm dòng mới.
    Nếu chưa có -> insert dòng mới.
    """
    clean_user_id, clean_asset_id = int(user_id), int(asset_id)
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT id FROM user_downloads
            WHERE user_id = ? AND asset_id = ?
        ''', (clean_user_id, clean_asset_id))
        existing = cursor.fetchone()

        if existing:
            cursor.execute('''
                UPDATE user_downloads
                SET format_selected = ?, download_status = 'SUCCESS', downloaded_at = datetime('now','localtime')
                WHERE id = ?
            ''', (quality, existing["id"]))
            conn.commit()
            return {"success": True, "download_id": existing["id"], "status": "SUCCESS", "duplicated": True}

        try:
            cursor.execute('''
                INSERT INTO user_downloads (user_id, asset_id, format_selected, download_status)
                VALUES (?, ?, ?, 'SUCCESS')
            ''', (clean_user_id, clean_asset_id, quality))
            conn.commit()
            return {"success": True, "download_id": cursor.lastrowid, "status": "SUCCESS", "duplicated": False}
        except sqlite3.IntegrityError:
            # Phòng race-condition: 2 request cùng lúc cùng asset -> request thua chỉ update lại dòng đã được insert.
            cursor.execute('''
                SELECT id FROM user_downloads WHERE user_id = ? AND asset_id = ?
            ''', (clean_user_id, clean_asset_id))
            row = cursor.fetchone()
            cursor.execute('''
                UPDATE user_downloads
                SET format_selected = ?, download_status = 'SUCCESS', downloaded_at = datetime('now','localtime')
                WHERE id = ?
            ''', (quality, row["id"]))
            conn.commit()
            return {"success": True, "download_id": row["id"], "status": "SUCCESS", "duplicated": True}


# ================================================================
# 3. TRUY XUẤT + SẮP XẾP KHO LƯU TRỮ CÁ NHÂN THEO METADATA
# ================================================================

def get_user_saved_media(user_id: int, sort_by: str = "date_saved", order: str = "DESC") -> list:
    """Lấy danh sách các video đã lưu (đã tải), hỗ trợ sắp xếp + kèm thumbnail."""
    clean_user_id = int(user_id)
    allowed_sort_fields = {
        "date_saved": "ud.downloaded_at",
        "views": "ma.view_count",
        "duration": "ma.duration_seconds",
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
            c.channel_name AS author_name,
            MAX(mc.thumbnail_url) AS thumbnail_url
        FROM user_downloads ud
        JOIN media_assets ma ON ud.asset_id = ma.id
        LEFT JOIN creators c ON ma.creator_id = c.id
        LEFT JOIN media_cache mc ON ma.id = mc.asset_id
        WHERE ud.user_id = ?
        GROUP BY ud.id, ma.id
        ORDER BY {sort_column} {direction}
    """

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, (clean_user_id,))
            return [dict(row) for row in cursor.fetchall()]
    except Exception as e:
        print(f"❌ Lỗi Sorting Engine: {e}")
        return []