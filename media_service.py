import sqlite3
from database_setup import get_connection

def get_or_create_creator(channel_id: str, channel_name: str, platform: str = 'youtube') -> int:
    """Kiểm tra xem tác giả/kênh đã tồn tại chưa, nếu chưa thì tạo mới và trả về ID."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT id FROM creators WHERE channel_id = ? AND platform = ?",
            (channel_id, platform)
        )
        row = cursor.fetchone()
        if row: return row['id']
            
        try:
            cursor.execute(
                "INSERT INTO creators (channel_id, channel_name, platform) VALUES (?, ?, ?)",
                (channel_id, channel_name, platform)
            )
            conn.commit()
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            cursor.execute(
                "SELECT id FROM creators WHERE channel_id = ? AND platform = ?",
                (channel_id, platform)
            )
            return cursor.fetchone()['id']

def add_media_asset(title: str, platform: str, external_id: str, source_url: str, 
                    creator_id: int = None, duration_seconds: int = None, 
                    view_count: int = 0, published_at: str = None) -> dict:
    """Thêm một bản ghi video mới từ URL vào CSDL kèm theo các Metadata phục vụ sắp xếp."""
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT INTO media_assets (
                    creator_id, title, platform, external_id, 
                    source_url, duration_seconds, view_count, published_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (creator_id, title, platform, external_id, 
                 source_url, duration_seconds, view_count, published_at)
            )
            conn.commit()
            return {"success": True, "asset_id": cursor.lastrowid}
            
    except sqlite3.IntegrityError as e:
        # ĐÃ SỬA LỖI: Nếu video đã tồn tại (trùng platform + external_id), truy xuất lại ID của nó và trả về thành công
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT id FROM media_assets WHERE platform = ? AND external_id = ?", (platform, external_id))
            row = cursor.fetchone()
            if row:
                return {"success": True, "asset_id": row['id']}
                
        return {"success": False, "message": "Video asset này đã tồn tại trong hệ thống.", "error": str(e)}
        
    except Exception as e:
        return {"success": False, "message": f"Lỗi hệ thống ghi nhận asset: {e}"}

def get_media_by_url(url: str) -> dict | None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM media_assets WHERE source_url = ?", (url.strip(),))
        row = cursor.fetchone()
        return dict(row) if row else None

def get_media_by_id(asset_id: int) -> dict | None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            """
            SELECT ma.*, c.channel_name AS author_name 
            FROM media_assets ma
            LEFT JOIN creators c ON ma.creator_id = c.id
            WHERE ma.id = ?
            """, 
            (asset_id,)
        )
        row = cursor.fetchone()
        return dict(row) if row else None