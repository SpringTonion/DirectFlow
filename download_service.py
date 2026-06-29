"""
download_service.py
-------------------
Xử lý logic tải xuống cá nhân:
  - Ghi nhận yêu cầu tải của user
  - Lấy lịch sử tải xuống cá nhân
"""

from database_setup import get_connection
from cache_service import get_cache

VALID_FORMATS = ('144p', '240p', '360p', '480p', '720p', '1080p', 'audio', 'thumbnail')
VALID_STATUSES = ('PENDING', 'SUCCESS', 'FAILED')

def record_download(asset_id: int, format_selected: str, user_id: int = None, ip_address: str = None) -> dict:
    """Ghi nhận yêu cầu tải của User và kiểm tra kho Cache."""
    if format_selected not in VALID_FORMATS:
        return {'success': False, 'message': f"Format '{format_selected}' không hợp lệ.", 'download_id': None}

    # Tìm link tải trong kho Cache
    cache_entry = get_cache(asset_id, format_selected)
    download_url = cache_entry['download_url'] if cache_entry else None
    status = 'SUCCESS' if download_url else 'FAILED'

    try:
        with get_connection() as conn:
            cursor = conn.cursor()

            # Ghi vào nhật ký cá nhân của User
            cursor.execute('''
                INSERT INTO user_downloads (user_id, asset_id, format_selected, download_status)
                VALUES (?, ?, ?, ?)
            ''', (user_id, asset_id, format_selected, status))
            download_id = cursor.lastrowid

            # Ghi log vết hệ thống chung
            cursor.execute('''
                INSERT INTO system_logs (user_id, asset_id, action_type, ip_address, details)
                VALUES (?, ?, 'DOWNLOAD', ?, ?)
            ''', (
                user_id, asset_id, ip_address,
                f"Download {format_selected} | Status: {status}"
            ))
            conn.commit()

        if download_url:
            return {
                'success': True,
                'download_id': download_id,
                'status': 'SUCCESS',
                'message': 'Link tải đã sẵn sàng.'
            }
        else:
            return {
                'success': True, 
                'download_id': download_id,
                'status': 'FAILED',
                'message': 'Cache đã hết hạn. Yêu cầu tải lại từ Server.'
            }

    except Exception as e:
        return {'success': False, 'message': str(e), 'download_id': None}

def get_user_download_history(user_id: int, page: int = 1, per_page: int = 20) -> dict:
    """Lấy lịch sử trạng thái tải của cá nhân (Dùng để Frontend render list Tiến trình)."""
    offset = (page - 1) * per_page
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM user_downloads WHERE user_id = ?", (user_id,))
        total = cursor.fetchone()[0]

        cursor.execute('''
            SELECT 
                ud.id, ud.asset_id, ma.title, ma.platform, 
                ud.format_selected, ud.download_status, ud.downloaded_at
            FROM user_downloads ud
            JOIN media_assets ma ON ud.asset_id = ma.id
            WHERE ud.user_id = ?
            ORDER BY ud.downloaded_at DESC
            LIMIT ? OFFSET ?
        ''', (user_id, per_page, offset))
        rows = [dict(r) for r in cursor.fetchall()]

    return {'total': total, 'page': page, 'per_page': per_page, 'history': rows}

def get_download_by_id(download_id: int) -> dict | None:
    """Xác thực ID tải xuống để cấp link file an toàn."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT ud.asset_id, ud.format_selected, ud.user_id
            FROM user_downloads ud
            WHERE ud.id = ?
        ''', (download_id,))
        row = cursor.fetchone()
    return dict(row) if row else None