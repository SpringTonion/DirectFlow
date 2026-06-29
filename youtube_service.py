import yt_dlp
import logging

logger = logging.getLogger(__name__)

def resolve_youtube_url(url: str) -> dict:
    ydl_opts = {
        'format': 'bestvideo+bestaudio/best',
        'noplaylist': True,
        'quiet': True,
        'no_warnings': True,
        'skip_download': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info_dict = ydl.extract_info(url, download=False)
            if not info_dict: raise ValueError("Không thể trích xuất dữ liệu.")

            title = info_dict.get('title', 'Video Không Tiêu Đề')
            creator = info_dict.get('uploader', 'Unknown Creator')
            channel_id = info_dict.get('channel_id', 'UnknownID')
            external_id = info_dict.get('id', '')
            duration = info_dict.get('duration', 0)          
            view_count = info_dict.get('view_count', 0)      
            
            thumbnail = info_dict.get('thumbnail')
            if not thumbnail and info_dict.get('thumbnails'):
                thumbs = info_dict.get('thumbnails')
                if isinstance(thumbs, list) and len(thumbs) > 0:
                    thumbnail = thumbs[-1].get('url', '')
            if isinstance(thumbnail, list):
                thumbnail = thumbnail[-1].get('url', '') if isinstance(thumbnail[-1], dict) else str(thumbnail[-1])
            if not isinstance(thumbnail, str):
                thumbnail = ''

            formats_list = []
            raw_formats = info_dict.get('formats', [])
            target_heights = { 1080: '1080p', 720: '720p', 480: '480p', 360: '360p', 240: '240p', 144: '144p' }

            # BƯỚC SỬA LỖI QUAN TRỌNG: Mở khóa lấy toàn bộ định dạng Video từ 1080p -> 144p
            for fmt in raw_formats:
                height = fmt.get('height')
                if height in target_heights and fmt.get('url'):
                    formats_list.append({ 'quality': target_heights[height], 'url': fmt['url'] })

            # Luồng Audio tách rời
            best_audio = info_dict.get('url')
            for fmt in reversed(raw_formats):
                if fmt.get('vcodec') == 'none' and fmt.get('acodec') != 'none' and fmt.get('url'):
                    best_audio = fmt['url']
                    break
            if best_audio: formats_list.append({ 'quality': 'audio', 'url': best_audio })

            # Thumbnail
            if thumbnail: formats_list.append({ 'quality': 'thumbnail', 'url': thumbnail })

            # Lọc bỏ các luồng trùng lặp độ phân giải
            unique_formats = {f['quality']: f for f in formats_list}.values()

            return {
                'title': title, 'creator': creator, 'channel_id': channel_id,
                'external_id': external_id, 'duration': duration, 'view_count': view_count,
                'thumbnail': thumbnail, 'formats': list(unique_formats)
            }

    except Exception as e:
        logger.error(f"Lỗi phân tích cú pháp Youtube URL: {e}")
        raise RuntimeError(str(e))