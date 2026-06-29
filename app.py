import os
from flask import send_file
import tempfile
import logging
from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required,
    get_jwt_identity, get_jwt
)
from dotenv import load_dotenv
from functools import wraps
from apscheduler.schedulers.background import BackgroundScheduler

import auth_service
import media_service
import cache_service
import download_service
import playlist_service
import user_library_service 
from youtube_service import resolve_youtube_url 
from database_setup import get_connection, create_master_database
from cache_service import get_cache
from merge_service import merge_video_audio # <-- ĐÃ IMPORT SERVICE MỚI

load_dotenv()
create_master_database()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
app.config['JWT_SECRET_KEY'] = os.getenv('JWT_SECRET_KEY', 'directflow_fallback_secret_key_2026')
app.config['JWT_TOKEN_LOCATION'] = ['headers', 'query_string']
app.config['JWT_QUERY_STRING_NAME'] = 'token'

CORS(app, resources={r"/*": {
    "origins": ["http://127.0.0.1:5500", "http://localhost:5500"],
    "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
    "allow_headers": ["Content-Type", "Authorization", "X-Requested-With", "Accept"]
}})

jwt = JWTManager(app)

def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        if get_jwt().get('role') != 'admin':
            return jsonify({'error': 'Cảnh báo: Khu vực chỉ dành cho Quản trị viên!'}), 403
        return fn(*args, **kwargs)
    return wrapper

scheduler = BackgroundScheduler()
scheduler.add_job(cache_service.cleanup_expired_cache, 'interval', hours=1, id='cache_cleanup')
scheduler.start()

# =====================================================================
# 1. API AUTH
# =====================================================================
@app.route('/auth/login', methods=['POST'])
def login():
    data = request.json or {}
    result = auth_service.login_user(data.get('email') or data.get('username'), data.get('password'), request.remote_addr)
    if not result['success']: return jsonify({'error': result['message']}), 400
    result['token'] = create_access_token(
        identity=str(result['user']['id']),
        additional_claims={'role': result['user']['role'], 'username': result['user']['username']}
    )
    return jsonify(result)

@app.route('/auth/register', methods=['POST'])
def register():
    data = request.json or {}
    result = auth_service.register_user(data.get('username'), data.get('password'), data.get('email'))
    if not result['success']: return jsonify({'error': result['message']}), 400
    return jsonify(result)

@app.route('/auth/logout', methods=['POST'])
@jwt_required()
def logout():
    auth_service.logout_user(int(get_jwt_identity()), request.remote_addr)
    return jsonify({'success': True})

@app.route('/users/me', methods=['GET'])
@jwt_required()
def get_me():
    user = auth_service.get_user_by_id(int(get_jwt_identity()))
    if not user: return jsonify({'error': 'User not found'}), 404
    return jsonify(user)

# =====================================================================
# 2. MEDIA RESOLVE
# =====================================================================
@app.route('/media/resolve', methods=['POST'])
@jwt_required()
def resolve_media():
    data = request.json or {}
    url = data.get('url')
    if not url: return jsonify({'error': 'URL trống'}), 400
    try:
        info = resolve_youtube_url(url)
        existing_asset = media_service.get_media_by_url(url)
        
        if existing_asset:
            asset_id = existing_asset['id']
        else:
            creator_id = media_service.get_or_create_creator(info.get('channel_id') or info.get('external_id', 'unknown'), info.get('creator', 'N/A'))
            asset_result = media_service.add_media_asset(info['title'], 'youtube', info.get('external_id', ''), url, creator_id, info['duration'], info.get('view_count', 0))
            if not asset_result['success']: return jsonify({'error': asset_result['message']}), 400
            asset_id = asset_result['asset_id']

        if 'formats' in info:
            saved = set()
            for fmt in info["formats"]:
                if fmt["quality"] in saved: continue
                saved.add(fmt["quality"])
                cache_service.save_cache(asset_id, fmt["quality"], fmt["url"], info.get("thumbnail", ""), 6)
        
        formats = cache_service.get_all_cache_for_asset(asset_id)
        return jsonify({
            'asset_id': asset_id, 'title': info.get('title',''), 'creator': info.get('creator','N/A'),
            'duration': info.get('duration',0), 'thumbnail': info.get('thumbnail',''), 'platform': 'youtube',
            'formats': [{'quality': f['quality'], 'format': 'mp4'} for f in formats]
        })
    except Exception as e:
        logger.exception(e)
        return jsonify({"error": str(e)}), 500

@app.route('/media/<int:asset_id>/formats', methods=['GET'])
def get_media_formats(asset_id):
    return jsonify([{'quality': f['quality'], 'format': 'mp4'} for f in cache_service.get_all_cache_for_asset(asset_id)])

# =====================================================================
# 3. DOWNLOADS & STORAGE (BỔ SUNG API XÓA KHO LƯU TRỮ)
# =====================================================================
@app.route('/users/me/downloads_sorted', methods=['GET'])
@jwt_required()
def get_my_downloads_with_sorting():
    return jsonify(user_library_service.get_user_saved_media(int(get_jwt_identity()), request.args.get('sort_by', 'date_saved'), request.args.get('order', 'DESC')))

@app.route('/downloads', methods=['POST'])
@jwt_required()
def create_download():
    data = request.json or {}
    result = download_service.record_download(int(data.get('asset_id')), data.get('quality'), int(get_jwt_identity()), request.remote_addr)
    if not result['success'] and result.get('download_id') is None: return jsonify({'error': result['message']}), 400
    return jsonify(result)

# API XÓA KHỎI KHO LƯU TRỮ
@app.route('/downloads/<int:asset_id>', methods=['DELETE'])
@jwt_required()
def delete_from_library(asset_id):
    user_id = get_jwt_identity()
    with get_connection() as conn:
        conn.execute("DELETE FROM user_downloads WHERE user_id = ? AND asset_id = ?", (int(user_id), asset_id))
        conn.commit()
    return jsonify({"success": True})

@app.route('/downloads/<int:download_id>/file', methods=['GET'])
@jwt_required()
def get_download_file(download_id):
    download = download_service.get_download_by_id(download_id)
    if not download: return jsonify({'error': 'Download không tồn tại'}), 404
    if download['user_id'] != int(get_jwt_identity()): return jsonify({'error': 'Unauthorized'}), 403

    quality = download['format_selected']

    if quality in ("audio", "thumbnail"):
        cache = cache_service.get_cache(download['asset_id'], quality)
        if not cache: return jsonify({'error': f'{quality} đã hết hạn'}), 404
        return redirect(cache['download_url'])

    # GỘP VIDEO + AUDIO BẰNG MERGE_SERVICE MỚI
    video_cache = cache_service.get_cache(download['asset_id'], quality)
    audio_cache = cache_service.get_cache(download['asset_id'], "audio")

    if not video_cache or not audio_cache:
        return jsonify({'error': 'Luồng Video hoặc Audio đã hết hạn, vui lòng cào lại link'}), 404

    try:
        output_path = merge_video_audio(video_cache["download_url"], audio_cache["download_url"])
        return send_file(output_path, as_attachment=True, download_name=f"DirectFlow_{quality}.mp4", mimetype="video/mp4")
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@app.route('/users/me/downloads', methods=['GET'])
@jwt_required()
def get_my_downloads():
    return jsonify(download_service.get_user_download_history(int(get_jwt_identity())))

# =====================================================================
# 4. PLAYLISTS
# =====================================================================
@app.route('/playlists/ensure_favorite', methods=['POST'])
@jwt_required()
def ensure_favorite_playlist():
    user_id = int(get_jwt_identity())
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM playlists WHERE user_id = ? AND name = 'Favorite'", (user_id,))
        row = cursor.fetchone()
        if row: return jsonify({'success': True, 'playlist_id': row['id']})
    return jsonify(playlist_service.create_playlist(user_id, "Favorite", is_public=False))

@app.route('/users/me/playlists', methods=['GET'])
@jwt_required()
def get_playlists():
    return jsonify(playlist_service.get_user_playlists(int(get_jwt_identity())))

@app.route('/playlists', methods=['POST'])
@jwt_required()
def create_playlist():
    data = request.json or {}
    result = playlist_service.create_playlist(int(get_jwt_identity()), data.get('name'), int(data.get('is_public', False)))
    if not result['success']: return jsonify({'error': result['message']}), 400
    return jsonify(result)

@app.route('/playlists/<int:playlist_id>/items', methods=['POST'])
@jwt_required()
def add_to_playlist(playlist_id):
    user_id = int(get_jwt_identity())
    asset_id = request.json.get('asset_id')
    
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT asset_id FROM playlist_items WHERE playlist_id = ? AND asset_id = ?", (playlist_id, int(asset_id)))
        if cursor.fetchone():
            conn.execute("DELETE FROM playlist_items WHERE playlist_id = ? AND asset_id = ?", (playlist_id, int(asset_id)))
            conn.commit()
            return jsonify({'success': True, 'action': 'removed', 'message': 'Đã bỏ khỏi danh sách'})

    result = playlist_service.add_to_playlist(playlist_id, int(asset_id), user_id)
    if not result['success']: return jsonify({'error': result['message']}), 400
    result['action'] = 'added'
    return jsonify(result)

@app.route('/playlists/<int:playlist_id>/items', methods=['GET'])
@jwt_required()
def get_playlist_items(playlist_id):
    result = playlist_service.get_playlist_contents(playlist_id, int(get_jwt_identity()))
    if not result['success']: return jsonify({'error': result['message']}), 400
    return jsonify(result['items'])

@app.route('/health', methods=['GET'])
def health(): return jsonify({'status': 'ok'})

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8000)))