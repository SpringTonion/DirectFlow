"""
cache_service.py
----------------
Quản lý bộ nhớ đệm (media_cache):
  - Lưu link tải vào cache (Sống mặc định 6 tiếng để tiết kiệm dung lượng)
  - Lấy link cache còn hiệu lực
  - Dọn dẹp tự động (Dùng cho BackgroundScheduler trong app.py)
"""

from datetime import datetime, timedelta
from database_setup import get_connection

VALID_QUALITIES = ('144p', '240p', '360p', '480p', '720p', '1080p', 'audio', 'thumbnail')
DEFAULT_EXPIRE_HOURS = 6

def save_cache(
    asset_id: int,
    quality: str,
    download_url: str,
    thumbnail_url: str = None,
    expire_hours: int = DEFAULT_EXPIRE_HOURS
) -> dict:
    """Lưu hoặc cập nhật link tải (UPSERT) vào bộ nhớ đệm."""
    if quality not in VALID_QUALITIES:
        return {'success': False, 'message': f"Quality '{quality}' không hợp lệ.", 'cache_id': None}
    if not download_url:
        return {'success': False, 'message': 'download_url không được để trống.', 'cache_id': None}

    expires_at = (datetime.now() + timedelta(hours=expire_hours)).strftime('%Y-%m-%d %H:%M:%S')

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                INSERT INTO media_cache (asset_id, quality, download_url, thumbnail_url, expires_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(asset_id, quality) DO UPDATE SET
                    download_url  = excluded.download_url,
                    thumbnail_url = excluded.thumbnail_url,
                    expires_at    = excluded.expires_at,
                    created_at    = datetime('now','localtime')
            ''', (asset_id, quality, download_url, thumbnail_url, expires_at))
            conn.commit()
            cache_id = cursor.lastrowid
        return {'success': True, 'message': 'Lưu cache thành công.', 'cache_id': cache_id}
    except Exception as e:
        return {'success': False, 'message': str(e), 'cache_id': None}

def get_cache(asset_id: int, quality: str) -> dict | None:
    """Lấy link cache ĐANG CÒN HẠN."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT * FROM media_cache
            WHERE asset_id = ? AND quality = ? AND expires_at > ?
        ''', (asset_id, quality, now))
        row = cursor.fetchone()
    return dict(row) if row else None

def get_all_cache_for_asset(asset_id: int) -> list:
    """Lấy tất cả các định dạng còn tải được của 1 video."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT quality, download_url FROM media_cache
            WHERE asset_id = ? AND expires_at > ?
            ORDER BY quality
        ''', (asset_id, now))
        return [dict(r) for r in cursor.fetchall()]

def cleanup_expired_cache() -> dict:
    """Dọn dẹp rác hệ thống (Được gọi tự động mỗi 1 giờ từ app.py)."""
    now = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM media_cache WHERE expires_at <= ?", (now,))
        deleted = cursor.rowcount

        if deleted > 0:
            conn.execute(
                "INSERT INTO system_logs (action_type, details) VALUES ('SYSTEM_CLEANUP', ?)",
                (f"Hệ thống tự động dọn dẹp {deleted} link cache hết hạn.",)
            )
        conn.commit()
    return {'deleted': deleted, 'message': f'Đã xóa {deleted} link.'}