import os
import logging
from flask import Flask, request, jsonify, redirect
from flask_cors import CORS
from flask_jwt_extended import (
    JWTManager, create_access_token, jwt_required,
    get_jwt_identity
)
from dotenv import load_dotenv
from apscheduler.schedulers.background import BackgroundScheduler

import auth_service
import media_service
import cache_service
import download_service
import playlist_service
import user_library_service # Tích hợp file dịch vụ sắp xếp & thư viện cá nhân mới
from youtube_service import resolve_youtube_url # Đã xóa search_youtube
from database_setup import get_connection, create_master_database

# ─── Load env và khởi tạo database ───
load_dotenv()
create_master_database()

# ─── Logging ───
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ─── Flask app ───
app = Flask(__name__)
_jwt_secret = os.getenv('JWT_SECRET_KEY')
if not _jwt_secret:
    raise RuntimeError(
        "JWT_SECRET_KEY chưa được thiết lập trong .env! "
        "Hãy tạo key ngẫu nhiên, ví dụ: python -c \"import secrets; print(secrets.token_hex(32))\""
    )
app.config['JWT_SECRET_KEY'] = _jwt_secret
app.config['JWT_TOKEN_LOCATION'] = ['headers', 'query_string']
app.config['JWT_QUERY_STRING_NAME'] = 'token'

# ─── CORS ───
CORS(app, resources={r"/*": {"origins": "*"}})

@app.after_request
def after_request(response):
    response.headers.add('Access-Control-Allow-Origin', '*')
    response.headers.add('Access-Control-Allow-Headers', 'Content-Type,Authorization')
    response.headers.add('Access-Control-Allow-Methods', 'GET,POST,PUT,DELETE,OPTIONS')
    return response

jwt = JWTManager(app)
from functools import wraps
from flask_jwt_extended import get_jwt

# ── Helper Gác Cổng Admin ──
def admin_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        claims = get_jwt()
        if claims.get('role') != 'admin':
            return jsonify({'error': 'Cảnh báo: Khu vực cấm. Chỉ dành cho Quản trị viên!'}), 403
        return fn(*args, **kwargs)
    return wrapper

# ─── Tự động dọn cache hết hạn mỗi giờ ───
scheduler = BackgroundScheduler()
scheduler.add_job(cache_service.cleanup_expired_cache, 'interval', hours=1, id='cache_cleanup')
scheduler.start()


# =====================================================================
# 1. NHÓM API TÀI KHOẢN (AUTH & USER)
# =====================================================================

@app.route('/auth/login', methods=['POST'])
def login():
    data = request.json
    identifier = data.get('email') or data.get('username')
    password = data.get('password')
    ip = request.remote_addr
    result = auth_service.login_user(identifier, password, ip)
    if not result['success']:
        return jsonify({'error': result['message']}), 400
    access_token = create_access_token(
        identity=result['user']['id'],
        additional_claims={'role': result['user']['role'], 'username': result['user']['username']}
    )
    result['token'] = access_token
    return jsonify(result)

@app.route('/auth/register', methods=['POST'])
def register():
    data = request.json
    username = data.get('username')
    password = data.get('password')
    email = data.get('email')
    result = auth_service.register_user(username, password, email)
    if not result['success']:
        return jsonify({'error': result['message']}), 400
    return jsonify(result)

@app.route('/auth/logout', methods=['POST'])
@jwt_required()
def logout():
    user_id = get_jwt_identity()
    auth_service.logout_user(user_id, request.remote_addr)
    return jsonify({'success': True, 'message': 'Logged out'})

@app.route('/users/me', methods=['GET'])
@jwt_required()
def get_me():
    user_id = get_jwt_identity()
    user = auth_service.get_user_by_id(user_id)
    if not user:
        return jsonify({'error': 'User not found'}), 404
    return jsonify(user)

@app.route('/users/me/stats', methods=['GET'])
@jwt_required()
def get_stats():
    user_id = get_jwt_identity()
    with get_connection() as conn:
        c = conn.cursor()
        c.execute("SELECT COUNT(*) FROM user_downloads WHERE user_id = ?", (user_id,))
        total = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM user_downloads WHERE user_id = ? AND date(downloaded_at) = date('now','localtime')", (user_id,))
        today = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM playlists WHERE user_id = ?", (user_id,))
        pl = c.fetchone()[0]
        c.execute("SELECT COUNT(*) FROM favorites WHERE user_id = ?", (user_id,))
        fav = c.fetchone()[0]
    return jsonify({
        'total_downloads': total,
        'today_downloads': today,
        'total_playlists': pl,
        'total_favorites': fav,
    })


# =====================================================================
# 2. NHÓM API XỬ LÝ MEDIA & LƯU TRỮ TỪ URL
# =====================================================================

@app.route('/media/<int:asset_id>/formats', methods=['GET'])
def get_media_formats(asset_id):
    """Trả về danh sách quality còn cache hợp lệ cho một asset."""
    formats = cache_service.get_all_cache_for_asset(asset_id)
    return jsonify([{'quality': f['quality'], 'format': 'mp4'} for f in formats])

@app.route('/media/resolve', methods=['POST'])
@jwt_required()
def resolve_media():
    """Cào dữ liệu từ URL, lưu thông tin lên Web và tạo Cache sẵn sàng"""
    data = request.json
    url = data.get('url')
    if not url:
        return jsonify({'error': 'Missing url'}), 400
    try:
        info = resolve_youtube_url(url)
        creator_id = None
        if info['creator'] and info['external_id']:
            real_channel_id = info.get('channel_id') or info['external_id']
            creator_id = media_service.get_or_create_creator(
                channel_id=real_channel_id,
                channel_name=info['creator'],
                platform='youtube'
            )
        
        # Bỏ category_ids vì đã xóa khỏi hệ thống
        asset_result = media_service.add_media_asset(
            title=info['title'],
            platform='youtube',
            external_id=info['external_id'],
            source_url=url,
            creator_id=creator_id,
            duration_seconds=info['duration'],
            view_count=info.get('view_count', 0),
            published_at=None
        )
        
        if not asset_result['success']:
            existing = media_service.get_media_by_url(url)
            if existing:
                asset_result = {'success': True, 'asset_id': existing['id']}
            else:
                return jsonify({'error': asset_result['message']}), 400
                
        asset_id = asset_result['asset_id']
        for fmt in info['formats']:
            cache_service.save_cache(
                asset_id=asset_id,
                quality=fmt['quality'],
                download_url=fmt['url'],
                thumbnail_url=info['thumbnail'],
                expire_hours=6
            )
        formats = cache_service.get_all_cache_for_asset(asset_id)
        return jsonify({
            'asset_id': asset_id,
            'title': info['title'],
            'creator': info['creator'],
            'duration': info['duration'],
            'thumbnail': info['thumbnail'],
            'platform': 'youtube',
            'formats': [{'quality': f['quality'], 'format': 'mp4'} for f in formats]
        })
    except Exception as e:
        logger.error(f"Resolve error: {e}")
        return jsonify({'error': str(e)}), 500


# =====================================================================
# 3. NHÓM API DOWNLOADS VÀ SẮP XẾP (SORTING)
# =====================================================================

@app.route('/users/me/downloads_sorted', methods=['GET'])
@jwt_required()
def get_my_downloads_with_sorting():
    """Lấy danh sách video đã lưu kèm tính năng sắp xếp theo Metadata (Mới)"""
    user_id = get_jwt_identity()
    sort_by = request.args.get('sort_by', 'date_saved')
    order = request.args.get('order', 'DESC')
    
    sorted_list = user_library_service.get_user_saved_media(user_id, sort_by=sort_by, order=order)
    return jsonify(sorted_list)

@app.route('/downloads', methods=['POST'])
@jwt_required()
def create_download():
    user_id = get_jwt_identity()
    data = request.json
    asset_id = data.get('asset_id')
    quality = data.get('quality')
    if not asset_id or not quality:
        return jsonify({'error': 'Missing asset_id or quality'}), 400
    if quality not in download_service.VALID_FORMATS:
        return jsonify({'error': f"Quality '{quality}' không hợp lệ."}), 400
        
    result = download_service.record_download(asset_id, quality, user_id, request.remote_addr)
    if not result['success'] and result.get('download_id') is None:
        return jsonify({'error': result['message']}), 400
    return jsonify(result)

@app.route('/downloads/<int:download_id>/file', methods=['GET'])
@jwt_required()
def get_download_file(download_id):
    """Điều hướng thẳng trình duyệt tới file MP4 để người dùng lưu về máy"""
    user_id = get_jwt_identity()
    download = download_service.get_download_by_id(download_id)
    if not download or download['user_id'] != user_id:
        return jsonify({'error': 'Download not found or unauthorized'}), 404
        
    cache_entry = cache_service.get_cache(download['asset_id'], download['format_selected'])
    if not cache_entry:
        return jsonify({'error': 'Link tải đã hết hạn, vui lòng tải lại'}), 404
    return redirect(cache_entry['download_url'])

@app.route('/users/me/downloads', methods=['GET'])
@jwt_required()
def get_my_downloads():
    """Lấy lịch sử tiến trình xử lý file (PENDING/SUCCESS)"""
    user_id = get_jwt_identity()
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    return jsonify(download_service.get_user_download_history(user_id, page, per_page))


# =====================================================================
# 4. NHÓM API YÊU THÍCH (FAVORITES) VÀ PLAYLISTS
# =====================================================================

@app.route('/favorites', methods=['POST'])
@jwt_required()
def add_favorite():
    user_id = get_jwt_identity()
    asset_id = request.json.get('asset_id')
    if not asset_id:
        return jsonify({'error': 'Missing asset_id'}), 400
        
    result = user_library_service.add_to_favorites(user_id, asset_id)
    if not result['success']:
        return jsonify({'error': result['message']}), 409 if 'trước' in result['message'] else 500
    return jsonify(result)

@app.route('/favorites/<int:asset_id>', methods=['DELETE'])
@jwt_required()
def remove_favorite(asset_id):
    user_id = get_jwt_identity()
    result = user_library_service.remove_from_favorites(user_id, asset_id)
    return jsonify(result)

@app.route('/users/me/favorites', methods=['GET'])
@jwt_required()
def get_favorites():
    user_id = get_jwt_identity()
    with get_connection() as conn:
        c = conn.cursor()
        c.execute('''
            SELECT f.asset_id, ma.title, ma.platform, ma.source_url, c.channel_name as creator_name
            FROM favorites f
            JOIN media_assets ma ON f.asset_id = ma.id
            LEFT JOIN creators c ON ma.creator_id = c.id
            WHERE f.user_id = ?
            ORDER BY f.added_at DESC
        ''', (user_id,))
        rows = [dict(r) for r in c.fetchall()]
    return jsonify(rows)

@app.route('/users/me/playlists', methods=['GET'])
@jwt_required()
def get_playlists():
    user_id = get_jwt_identity()
    return jsonify(playlist_service.get_user_playlists(user_id))

@app.route('/playlists', methods=['POST'])
@jwt_required()
def create_playlist():
    user_id = get_jwt_identity()
    data = request.json
    name = data.get('name')
    is_public = data.get('is_public', False)
    result = user_library_service.create_playlist(user_id, name, int(is_public))
    if not result['success']:
        return jsonify({'error': result['message']}), 400
    return jsonify(result)

@app.route('/playlists/<int:playlist_id>/items', methods=['POST'])
@jwt_required()
def add_to_playlist(playlist_id):
    user_id = get_jwt_identity() # Cần logic check quyền sở hữu (bỏ qua để đơn giản)
    asset_id = request.json.get('asset_id')
    if not asset_id:
        return jsonify({'error': 'Missing asset_id'}), 400
    result = user_library_service.add_to_playlist(playlist_id, asset_id)
    if not result['success']:
        return jsonify({'error': result['message']}), 400
    return jsonify(result)

# ── Health ──
@app.route('/health', methods=['GET'])
def health():
    return jsonify({'status': 'ok'})

# =====================================================================
# 5. NHÓM API QUẢN TRỊ HỆ THỐNG (ADMIN DASHBOARD)
# =====================================================================

@app.route('/admin/users', methods=['GET'])
@jwt_required()
@admin_required
def admin_get_users():
    """Lấy danh sách User kèm Sort"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)
    sort_by = request.args.get('sort_by', 'created_at')
    order = request.args.get('order', 'DESC')
    return jsonify(auth_service.get_all_users_admin(page, per_page, sort_by, order))

@app.route('/admin/users/<int:target_user_id>', methods=['PUT'])
@jwt_required()
@admin_required
def admin_modify_user(target_user_id):
    """Sửa thông tin: Khóa mõm hoặc phong chức"""
    data = request.json
    is_active = data.get('is_active', 1)
    role = data.get('role', 'member')
    return jsonify(auth_service.modify_user_admin(target_user_id, int(is_active), role))

@app.route('/admin/users/<int:target_user_id>', methods=['DELETE'])
@jwt_required()
@admin_required
def admin_delete_user(target_user_id):
    """Trảm: Xóa vĩnh viễn user"""
    # Không cho phép tự xóa chính mình
    if target_user_id == get_jwt_identity():
        return jsonify({'error': 'Không thể tự sát tài khoản Admin đang đăng nhập!'}), 400
        
    return jsonify(auth_service.delete_user_admin(target_user_id))

if __name__ == '__main__':
    port = int(os.getenv('PORT', 8000))
    app.run(host='0.0.0.0', port=port)