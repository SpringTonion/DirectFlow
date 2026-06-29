"""
category_service.py
-------------------
Quản lý danh mục nội dung (categories):
  - Tạo / Sửa / Xóa category
  - Gán / Bỏ gán category cho media
  - Lấy danh sách categories
  - Lấy media theo category
"""

from database_setup import get_connection

# ─────────────────────────────────────────────
# CRUD CATEGORY
# ─────────────────────────────────────────────

def create_category(name: str) -> dict:
    name = name.strip()
    if not name:
        return {'success': False, 'message': 'Tên category không được để trống.', 'category_id': None}

    try:
        with get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("INSERT INTO categories (name) VALUES (?)", (name,))
            conn.commit()
            return {'success': True, 'message': 'Tạo category thành công.', 'category_id': cursor.lastrowid}
    except Exception as e:
        if 'UNIQUE' in str(e):
            return {'success': False, 'message': f"Category '{name}' đã tồn tại.", 'category_id': None}
        return {'success': False, 'message': str(e), 'category_id': None}

def update_category(category_id: int, name: str) -> dict:
    name = name.strip()
    if not name:
        return {'success': False, 'message': 'Tên không được để trống.'}

    try:
        with get_connection() as conn:
            conn.execute("UPDATE categories SET name = ? WHERE id = ?", (name, category_id))
            conn.commit()
        return {'success': True, 'message': 'Cập nhật thành công.'}
    except Exception as e:
        if 'UNIQUE' in str(e):
            return {'success': False, 'message': 'Tên category đã tồn tại.'}
        return {'success': False, 'message': str(e)}

def delete_category(category_id: int) -> dict:
    with get_connection() as conn:
        conn.execute("DELETE FROM categories WHERE id = ?", (category_id,))
        conn.commit()
    return {'success': True, 'message': 'Đã xóa category.'}

def get_all_categories() -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT
                c.id, c.name,
                COUNT(mcm.asset_id) AS media_count
            FROM categories c
            LEFT JOIN media_category_map mcm ON c.id = mcm.category_id
            GROUP BY c.id
            ORDER BY c.name
        ''')
        return [dict(r) for r in cursor.fetchall()]

def get_category_by_id(category_id: int) -> dict | None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM categories WHERE id = ?", (category_id,))
        row = cursor.fetchone()
    return dict(row) if row else None

def get_category_by_name(name: str) -> dict | None:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT * FROM categories WHERE name = ?", (name.strip(),))
        row = cursor.fetchone()
    return dict(row) if row else None

# ─────────────────────────────────────────────
# GÁN / BỎ GÁN CATEGORY CHO MEDIA
# ─────────────────────────────────────────────

def assign_category_to_media(asset_id: int, category_id: int) -> dict:
    try:
        with get_connection() as conn:
            conn.execute(
                "INSERT OR IGNORE INTO media_category_map (asset_id, category_id) VALUES (?, ?)",
                (asset_id, category_id)
            )
            conn.commit()
        return {'success': True, 'message': 'Đã gán category.'}
    except Exception as e:
        return {'success': False, 'message': str(e)}

def remove_category_from_media(asset_id: int, category_id: int) -> dict:
    with get_connection() as conn:
        conn.execute(
            "DELETE FROM media_category_map WHERE asset_id = ? AND category_id = ?",
            (asset_id, category_id)
        )
        conn.commit()
    return {'success': True, 'message': 'Đã bỏ gán category.'}

def set_categories_for_media(asset_id: int, category_ids: list) -> dict:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM media_category_map WHERE asset_id = ?", (asset_id,))
        for cat_id in category_ids:
            cursor.execute(
                "INSERT OR IGNORE INTO media_category_map (asset_id, category_id) VALUES (?, ?)",
                (asset_id, cat_id)
            )
        conn.commit()
    return {'success': True, 'message': f'Đã cập nhật {len(category_ids)} category cho media.'}

def get_categories_of_media(asset_id: int) -> list:
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute('''
            SELECT c.id, c.name
            FROM categories c
            JOIN media_category_map mcm ON c.id = mcm.category_id
            WHERE mcm.asset_id = ?
            ORDER BY c.name
        ''', (asset_id,))
        return [dict(r) for r in cursor.fetchall()]

# ─────────────────────────────────────────────
# LẤY MEDIA THEO CATEGORY
# ─────────────────────────────────────────────

def get_media_by_category(category_id: int, page: int = 1, per_page: int = 20) -> dict:
    offset = (page - 1) * per_page
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT COUNT(*) FROM media_category_map WHERE category_id = ?",
            (category_id,)
        )
        total = cursor.fetchone()[0]

        cursor.execute('''
            SELECT
                ma.id, ma.title, ma.platform, ma.source_url,
                ma.duration_seconds, ma.view_count,
                c.channel_name
            FROM media_assets ma
            JOIN media_category_map mcm ON ma.id = mcm.asset_id
            LEFT JOIN creators c ON ma.creator_id = c.id
            WHERE mcm.category_id = ?
            ORDER BY ma.id DESC
            LIMIT ? OFFSET ?
        ''', (category_id, per_page, offset))
        rows = [dict(r) for r in cursor.fetchall()]

    return {'total': total, 'page': page, 'per_page': per_page, 'results': rows}

def get_or_create_category(name: str) -> int:
    existing = get_category_by_name(name)
    if existing:
        return existing['id']
    result = create_category(name)
    return result['category_id']