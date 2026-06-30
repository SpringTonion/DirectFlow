import os
import uuid
import tempfile
import subprocess
import logging

logger = logging.getLogger(__name__)
TEMP_DIR = tempfile.gettempdir()

def merge_video_audio(video_url: str, audio_url: str) -> str:
    """Sử dụng FFmpeg ghép trực tiếp luồng stream HTTPS, không cần tải tạm về ổ cứng."""
    uid = str(uuid.uuid4())
    output_path = os.path.join(TEMP_DIR, uid + ".mp4")

    try:
        subprocess.run([
            "./ffmpeg.exe",
            "-y",
            "-i", video_url,
            "-i", audio_url,
            "-c:v", "copy",
            "-c:a", "aac",
            "-movflags", "+faststart",
            output_path
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        return output_path
        
    except FileNotFoundError:
        raise RuntimeError("LỖI HỆ THỐNG: Máy tính chưa cài đặt FFmpeg. Vui lòng cài FFmpeg để ghép file!")
    except subprocess.CalledProcessError as e:
        if os.path.exists(output_path):
            os.remove(output_path)
        raise RuntimeError("Không thể ghép luồng Video và Audio. Link có thể đã bị YouTube chặn/hết hạn.")
    