"""
youtube_service.py
------------------
Sử dụng thư viện yt-dlp để trích xuất trực tiếp luồng stream video thô từ URL YouTube.
Đã sửa lỗi định dạng mảng Thumbnail gây crash bộ giải mã.
"""

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
            if not info_dict: raise ValueError("Không thể trích xuất dữ liệu từ đường dẫn này.")

            title = info_dict.get('title', 'Video Không Tiêu Đề')
            creator = info_dict.get('uploader', 'Unknown Creator')
            channel_id = info_dict.get('channel_id', 'UnknownID')
            external_id = info_dict.get('id', '')
            duration = info_dict.get('duration', 0)          
            view_count = info_dict.get('view_count', 0)      
            
            # ĐÃ SỬA LỖI BỘ GIẢI MÃ: Ép kiểu Thumbnail tránh lỗi truyền Mảng (List/Dict) vào Database
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

            formats_list = []

            raw_formats = info_dict.get("formats", [])

            target_heights = {
                1080: "1080p",
                720: "720p",
                480: "480p",
                360: "360p",
                240: "240p",
                144: "144p"
            }

            best_audio = None

            # ==========================
            # Video ONLY
            # ==========================

            video_streams = {}

            for fmt in raw_formats:

                if (
                    fmt.get("vcodec") != "none"
                    and fmt.get("acodec") == "none"
                    and fmt.get("height") in target_heights
                    and fmt.get("url")
                ):

                    quality = target_heights[fmt["height"]]

                    # lấy bitrate cao nhất
                    if (
                        quality not in video_streams
                        or fmt.get("tbr", 0) > video_streams[quality].get("tbr", 0)
                    ):
                        video_streams[quality] = fmt


            for quality, fmt in video_streams.items():

                formats_list.append({
                    "quality": quality,
                    "url": fmt["url"]
                })

            # ==========================
            # Audio ONLY
            # ==========================

            for fmt in raw_formats:

                if (
                    fmt.get("vcodec") == "none"
                    and fmt.get("acodec") != "none"
                    and fmt.get("url")
                ):

                    if (
                        best_audio is None
                        or fmt.get("abr", 0) > best_audio.get("abr", 0)
                    ):
                        best_audio = fmt

            if best_audio:

                formats_list.append({
                    "quality": "audio",
                    "url": best_audio["url"]
                })

            # ==========================
            # Thumbnail
            # ==========================

            if thumbnail:

                formats_list.append({
                    "quality": "thumbnail",
                    "url": thumbnail
                })

            # ==========================
            # Progressive fallback
            # ==========================

            if len(video_streams) == 0:

                for fmt in raw_formats:

                    if (
                        fmt.get("vcodec") != "none"
                        and fmt.get("acodec") != "none"
                        and fmt.get("url")
                    ):

                        h = fmt.get("height")

                        if h in target_heights:

                            formats_list.append({
                                "quality": target_heights[h],
                                "url": fmt["url"]
                            })

                            break
        return {
            "title": title,
            "creator": creator,
            "channel_id": channel_id,
            "external_id": external_id,
            "duration": duration,
            "view_count": view_count,
            "thumbnail": thumbnail,
            "formats": formats_list
        }

    except Exception as e:
        logger.error(f"Lỗi phân tích cú pháp Youtube URL: {e}")
        raise RuntimeError(str(e))