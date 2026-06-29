"""
youtube_service.py
------------------
Sử dụng thư viện yt-dlp để trích xuất trực tiếp luồng stream video thô từ URL YouTube.
Đồng thời thu thập các Metadata (lượt xem, thời lượng, tiêu đề) để phục vụ tính năng Sắp xếp.
"""

import yt_dlp
import logging

logger = logging.getLogger(__name__)

def resolve_youtube_url(url: str) -> dict:
    """
    Dán đường dẫn URL YouTube -> Bóc tách thông tin thô và trả về Metadata
    kèm theo mảng cấu trúc các mức độ phân giải có sẵn từ YouTube.
    """
    # Cấu hình yt-dlp chỉ lấy thông tin (Info Extraction), không tải file vật lý về server
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Tiến hành cào thông tin thô từ máy chủ YouTube
            info_dict = ydl.extract_info(url, download=False)
            
            if not info_dict:
                raise ValueError("Không thể trích xuất dữ liệu từ đường dẫn này.")

            # Trích xuất các Metadata cốt lõi phục vụ tính năng Sort của Frontend
            title = info_dict.get('title', 'Video Không Tiêu Đề')
            creator = info_dict.get('uploader', 'Unknown Creator')
            channel_id = info_dict.get('channel_id', 'UnknownID')
            external_id = info_dict.get('id', '')
            duration = info_dict.get('duration', 0)          # Phục vụ Sort theo thời lượng
            view_count = info_dict.get('view_count', 0)      # Phục vụ Sort theo lượt xem
            thumbnail = info_dict.get('thumbnail', '')

            # Lọc và ép cấu trúc luồng định dạng (Formats) sang chuẩn của media_cache
            formats_list = []
            raw_formats = info_dict.get('formats', [])

            # 1. Định nghĩa các mức chất lượng video muốn giữ lại
            target_qualities = {
                '1080p': '1080p',
                '720p': '720p',
                '480p': '480p',
                '360p': '360p',
                '240p': '240p',
                '144p': '144p'
            }

            # Lọc các luồng video có sẵn từ cấu trúc thô của YouTube
            for fmt in raw_formats:
                q_note = fmt.get('format_note') or fmt.get('resolution')
                if q_note and q_note in target_qualities:
                    q_name = target_qualities[q_note]
                    if fmt.get('url'):
                        formats_list.append({
                            'quality': q_name,
                            'url': fmt['url']
                        })

            # 2. Tạo luồng trích xuất âm thanh mặc định (Audio Only)
            best_audio = info_dict.get('url') # Dự phòng
            for fmt in reversed(raw_formats):
                if fmt.get('vcodec') == 'none' and fmt.get('acodec') != 'none' and fmt.get('url'):
                    best_audio = fmt['url']
                    break
            
            formats_list.append({
                'quality': 'audio',
                'url': best_audio
            })

            # 3. Tạo luồng ảnh bìa mặc định (Thumbnail)
            if thumbnail:
                formats_list.append({
                    'quality': 'thumbnail',
                    'url': thumbnail
                })

            # Loại bỏ các phần tử trùng mức chất lượng trong mảng bằng dict
            unique_formats = {f['quality']: f for f in formats_list}.values()

            return {
                'title': title,
                'creator': creator,
                'channel_id': channel_id,
                'external_id': external_id,
                'duration': duration,
                'view_count': view_count,
                'thumbnail': thumbnail,
                'formats': list(unique_formats)
            }

    except Exception as e:
        logger.error(f"Lỗi phân tích cú pháp Youtube URL: {e}")
        raise RuntimeError(f"Bộ cào dữ liệu thất bại: {str(e)}")