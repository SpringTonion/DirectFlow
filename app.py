import os
from flask import send_file
import tempfile
import subprocess
import uuid
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
import user_library_service 
from youtube_service import resolve_youtube_url 
from database_setup import get_connection, create_master_database
from cache_service import get_cache

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
    @jwt_required()
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

@app.route('/users/me/password', methods=['PUT'])
@jwt_required()
def update_my_password():
    data = request.json or {}
    res = auth_service.change_password(int(get_jwt_identity()), data.get('old_password'), data.get('new_password'))
    if not res['success']: return jsonify({'error': res['message']}), 400
    return jsonify({'success': True})

@app.route('/users/me', methods=['DELETE'])
@jwt_required()
def delete_my_account():
    with get_connection() as conn:
        conn.execute("DELETE FROM users WHERE id = ?", (int(get_jwt_identity()),))
        conn.commit()
    return jsonify({'success': True})

# =====================================================================
# 2. MEDIA RESOLVE (ĐÃ MỞ KHÓA CHO KHÁCH: optional=True)
# =====================================================================
@app.route('/media/resolve', methods=['POST'])
@jwt_required(optional=True)
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
# 3. DOWNLOADS & GUEST (VIẾT LẠI SQL TRỰC TIẾP, AN TOÀN TUYỆT ĐỐI)
# =====================================================================
@app.route('/users/me/downloads_sorted', methods=['GET'])
@jwt_required()
def get_my_downloads_with_sorting():
    user_id = int(get_jwt_identity())
    sort_by = request.args.get('sort_by', 'date_saved')
    order = request.args.get('order', 'DESC')
    return jsonify(user_library_service.get_user_saved_media(user_id, sort_by, order))

@app.route('/downloads', methods=['POST'])
@jwt_required()
def create_download():
    data = request.json or {}
    asset_id = data.get('asset_id')
    quality = data.get('quality')
    user_id = int(get_jwt_identity())

    if not asset_id or not quality: 
        return jsonify({'error': 'Thiếu tham số tải'}), 400

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            # Ghi trực tiếp vào kho, không qua service để tránh lỗi
            cursor.execute('''
                INSERT INTO user_downloads (user_id, asset_id, format_selected, download_status)
                VALUES (?, ?, ?, 'SUCCESS')
            ''', (user_id, int(asset_id), quality))
            download_id = cursor.lastrowid
            conn.commit()
        return jsonify({'success': True, 'download_id': download_id, 'status': 'SUCCESS'})
    except Exception as e:
        return jsonify({'error': f"Lỗi lưu kho: {str(e)}"}), 500

@app.route('/downloads/guest/file', methods=['GET'])
def guest_download_file():
    asset_id = request.args.get('asset_id', type=int)
    quality = request.args.get('quality')
    if not asset_id or not quality: return jsonify({'error': 'Thiếu tham số'}), 400
    
    if quality in ("audio", "thumbnail"):
        cache = cache_service.get_cache(asset_id, quality)
        return redirect(cache['download_url']) if cache else ("Hết hạn", 404)
        
    vc = cache_service.get_cache(asset_id, quality)
    ac = cache_service.get_cache(asset_id, "audio")
    if not vc or not ac: return "Luồng đã hết hạn, vui lòng cào lại link", 404
    
    try: 
        from merge_service import merge_video_audio
        return send_file(merge_video_audio(vc["download_url"], ac["download_url"]), as_attachment=True, download_name=f"Guest_{quality}.mp4", mimetype="video/mp4")
    except Exception as e: return f"Lỗi đóng gói: {str(e)}", 500

@app.route('/downloads/<int:download_id>/file', methods=['GET'])
@jwt_required()
def get_download_file(download_id):
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT asset_id, format_selected, user_id FROM user_downloads WHERE id = ?", (download_id,))
            download = cursor.fetchone()
            
        if not download or download['user_id'] != int(get_jwt_identity()): 
            return jsonify({'error': 'Unauthorized'}), 403

        quality = download['format_selected']
        if quality in ("audio", "thumbnail"):
            cache = cache_service.get_cache(download['asset_id'], quality)
            return redirect(cache['download_url']) if cache else (jsonify({'error': 'Hết hạn'}), 404)

        video_cache = cache_service.get_cache(download['asset_id'], quality)
        audio_cache = cache_service.get_cache(download['asset_id'], "audio")
        if not video_cache or not audio_cache: return jsonify({'error': 'Video/Audio hết hạn'}), 404

        from merge_service import merge_video_audio
        output_path = merge_video_audio(video_cache["download_url"], audio_cache["download_url"])
        return send_file(output_path, as_attachment=True, download_name=f"DirectFlow_{quality}.mp4", mimetype="video/mp4")
    except Exception as e: 
        return jsonify({"error": str(e)}), 500

@app.route('/users/me/downloads', methods=['GET'])
@jwt_required()
def get_my_downloads():
    user_id = int(get_jwt_identity())
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute('''
                SELECT ud.id, ud.asset_id, ma.title, ma.platform, ud.format_selected, ud.download_status, ud.downloaded_at
                FROM user_downloads ud
                JOIN media_assets ma ON ud.asset_id = ma.id
                WHERE ud.user_id = ?
                ORDER BY ud.downloaded_at DESC
            ''', (user_id,))
            return jsonify({'history': [dict(r) for r in cursor.fetchall()]})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/downloads/<int:download_id>', methods=['DELETE'])
@jwt_required()
def delete_download(download_id):
    user_id = int(get_jwt_identity())
    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT user_id FROM user_downloads WHERE id = ?", (download_id,))
            row = cursor.fetchone()
            if not row or row['user_id'] != user_id:
                return jsonify({'error': 'Bạn không có quyền xóa mục này.'}), 403
            conn.execute("DELETE FROM user_downloads WHERE id = ?", (download_id,))
            conn.commit()
        return jsonify({'success': True, 'message': 'Đã xóa khỏi kho lưu trữ.'})
    except Exception as e:
        return jsonify({'error': str(e)}), 500


# =====================================================================
# 4. PLAYLISTS (Đi qua user_library_service — đã gộp playlist_service.py)
# =====================================================================
@app.route('/users/me/playlists', methods=['GET'])
@jwt_required()
def get_playlists():
    user_id = int(get_jwt_identity())
    return jsonify(user_library_service.get_user_playlists(user_id))

@app.route('/playlists', methods=['POST'])
@jwt_required()
def create_playlist():
    user_id = int(get_jwt_identity())
    name = (request.json or {}).get('name')
    result = user_library_service.create_playlist(user_id, name)
    if not result['success']: return jsonify({'error': result['message']}), 400
    return jsonify(result)

@app.route('/playlists/<int:playlist_id>', methods=['DELETE'])
@jwt_required()
def delete_playlist(playlist_id):
    user_id = int(get_jwt_identity())
    result = user_library_service.delete_playlist(playlist_id, user_id)
    if not result['success']: return jsonify({'error': result['message']}), 403
    return jsonify(result)

@app.route('/playlists/<int:playlist_id>/items', methods=['POST'])
@jwt_required()
def add_to_playlist(playlist_id):
    user_id = int(get_jwt_identity())
    asset_id = int((request.json or {}).get('asset_id'))
    result = user_library_service.add_to_playlist(playlist_id, asset_id, user_id)
    if not result['success']: return jsonify({'error': result['message']}), 403
    return jsonify(result)

@app.route('/playlists/<int:playlist_id>/items', methods=['GET'])
@jwt_required()
def get_playlist_items(playlist_id):
    user_id = int(get_jwt_identity())
    result = user_library_service.get_playlist_contents(playlist_id, user_id)
    if not result['success']: return jsonify({'error': result['message']}), 403
    return jsonify(result['items'])

@app.route('/playlists/<int:playlist_id>/items/<int:asset_id>', methods=['DELETE'])
@jwt_required()
def remove_playlist_item(playlist_id, asset_id):
    user_id = int(get_jwt_identity())
    result = user_library_service.add_to_playlist(playlist_id, asset_id, user_id)  # toggle: nếu đang có sẽ xóa
    if not result['success']: return jsonify({'error': result['message']}), 403
    return jsonify(result)

# =====================================================================
# 4B. FAVORITES (bảng `favorites` riêng — kết nối thật vào DB)
# =====================================================================
@app.route('/users/me/favorites', methods=['GET'])
@jwt_required()
def get_my_favorites():
    user_id = int(get_jwt_identity())
    return jsonify(user_library_service.get_user_favorites(user_id))

@app.route('/favorites/toggle', methods=['POST'])
@jwt_required()
def toggle_favorite():
    user_id = int(get_jwt_identity())
    asset_id = (request.json or {}).get('asset_id')
    if not asset_id: return jsonify({'error': 'Thiếu asset_id'}), 400
    result = user_library_service.toggle_favorite(user_id, asset_id)
    if not result['success']: return jsonify({'error': result['message']}), 400
    return jsonify(result)

# =====================================================================
# 5. ADMIN DASHBOARD (PHỤC HỒI API)
# =====================================================================
@app.route('/admin/dashboard', methods=['GET'])
@admin_required
def admin_dashboard():
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) FROM users")
        users_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM media_assets")
        assets_count = cursor.fetchone()[0]
        cursor.execute("SELECT COUNT(*) FROM user_downloads")
        dl_count = cursor.fetchone()[0]
    return jsonify({
        'total_users': users_count,
        'total_assets': assets_count,
        'total_downloads': dl_count
    })

@app.route('/admin/users', methods=['GET'])
@admin_required
def admin_get_users():
    return jsonify(auth_service.get_all_users_admin(request.args.get('page', 1, type=int), 50))

@app.route('/admin/users/<int:target_user_id>', methods=['PUT'])
@admin_required
def admin_modify_user(target_user_id):
    data = request.json or {}
    return jsonify(auth_service.modify_user_admin(target_user_id, int(data.get('is_active', 1)), data.get('role', 'member')))

@app.route('/admin/users/<int:target_user_id>', methods=['DELETE'])
@admin_required
def admin_delete_user(target_user_id):
    if target_user_id == int(get_jwt_identity()): return jsonify({'error': 'Cannot delete self'}), 400
    return jsonify(auth_service.delete_user_admin(target_user_id))

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.getenv('PORT', 8000)))