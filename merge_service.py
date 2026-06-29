import os
import uuid
import tempfile
import subprocess
import requests

TEMP_DIR = "temp"

os.makedirs(TEMP_DIR, exist_ok=True)


def download_file(url, filename):
    r = requests.get(url, stream=True)

    with open(filename, "wb") as f:
        for chunk in r.iter_content(1024 * 1024):
            if chunk:
                f.write(chunk)


def merge_video_audio(video_url, audio_url):
    uid = str(uuid.uuid4())

    video_file = os.path.join(TEMP_DIR, uid + "_video.mp4")
    audio_file = os.path.join(TEMP_DIR, uid + "_audio.m4a")
    output_file = os.path.join(TEMP_DIR, uid + ".mp4")

    download_file(video_url, video_file)
    download_file(audio_url, audio_file)

    subprocess.run([
        "ffmpeg",
        "-y",
        "-i", video_file,
        "-i", audio_file,
        "-c:v", "copy",
        "-c:a", "copy",
        output_file
    ])

    os.remove(video_file)
    os.remove(audio_file)

    return output_file