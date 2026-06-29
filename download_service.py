"""
download_service.py
-------------------
Xử lý logic tải xuống cá nhân:
  - Ép tải Video luôn đi kèm Audio tích hợp
  - Hỗ trợ tách luồng Audio riêng và Thumbnail riêng biệt
"""

from database_setup import get_connection
from cache_service import get_cache

# Khớp tuyệt đối với CHECK constraint trong bảng media_cache và user_downloads
VALID_FORMATS = ('144p', '240p', '360p', '480p', '720p', '1080p', 'audio', 'thumbnail')
VALID_STATUSES = ('PENDING', 'SUCCESS', 'FAILED')

def record_download(asset_id: int, format_selected: str, user_id: int = None, ip_address: str = None) -> dict:
    """Ghi nhận yêu cầu tải của User và kiểm tra luồng tích hợp hình tiếng."""
    if format_selected not in VALID_FORMATS:
        return {'success': False, 'message': f"Format '{format_selected}' không hợp lệ.", 'download_id': None}

    # Đồng bộ ép kiểu dữ liệu Identity
    clean_user_id = int(user_id) if user_id is not None else None

    # Tìm link luồng tải trong kho Cache
    cache_entry = get_cache(asset_id, format_selected)
    
    # GIẢI CỨU ĐỊNH DẠNG: Nếu user chọn tải Video mà bản cache đó bị thiếu, 
    # tự động tìm luồng tích hợp sẵn tốt nhất làm dự phòng.
    if not cache_entry and format_selected not in ('audio', 'thumbnail'):
        for backup_format in ('720p', '360p', '1080p'):
            cache_entry = get_cache(asset_id, backup_format)
            if cache_entry:
                format_selected = backup_format
                break

    download_url = cache_entry['download_url'] if cache_entry else None
    status = 'SUCCESS' if download_url else 'FAILED'

    try:
        with get_connection() as conn:
            cursor = conn.cursor()

            # Ghi vào bảng user_downloads
            cursor.execute('''
                INSERT INTO user_downloads (user_id, asset_id, format_selected, download_status)
                VALUES (?, ?, ?, ?)
            ''', (clean_user_id, asset_id, format_selected, status))
            download_id = cursor.lastrowid

            # ĐÃ SỬA LỖI CHÍNH MẠNG Ở ĐÂY: Dùng .upper() của Python thay vì .toUpperCase() của JS
            cursor.execute('''
                INSERT INTO system_logs (user_id, asset_id, action_type, ip_address, details)
                VALUES (?, ?, 'DOWNLOAD', ?, ?)
            ''', (
                clean_user_id, asset_id, ip_address,
                f"Tải luồng: {format_selected.upper()} | Trạng thái: {status}"
            ))
            conn.commit()

        if download_url:
            return {
                'success': True,
                'download_id': download_id,
                'status': 'SUCCESS',
                'message': 'Đường luồng tải đã sẵn sàng phát.'
            }
        else:
            return {
                'success': False, 
                'download_id': download_id,
                'status': 'FAILED',
                'message': 'Bộ trích xuất luồng của video này tạm thời gián đoạn.'
            }

    except Exception as e:
        return {'success': False, 'message': str(e), 'download_id': None}

def get_user_download_history(user_id: int, page: int = 1, per_page: int = 20) -> dict:
    """Lấy lịch sử trạng thái tải của cá nhân (Dùng để Frontend render list Tiến trình)."""
    clean_user_id = int(user_id)
    offset = (page - 1) * per_page
    with get_connection() as conn:
        cursor = conn.cursor()

        cursor.execute("SELECT COUNT(*) FROM user_downloads WHERE user_id = ?", (clean_user_id,))
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
        ''', (clean_user_id, per_page, offset))
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