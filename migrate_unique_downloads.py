

import sqlite3
from database_setup import get_db_path

def column_unique_is_correct(conn) -> bool:
    """Kiểm tra xem bảng user_downloads đã có UNIQUE(user_id, asset_id) hay chưa."""
    cursor = conn.cursor()
    cursor.execute("SELECT sql FROM sqlite_master WHERE type='table' AND name='user_downloads'")
    row = cursor.fetchone()
    if not row:
        return True  # bảng chưa tồn tại, create_master_database() sẽ tự tạo đúng
    table_sql = row[0]
    return "UNIQUE (user_id, asset_id)," in table_sql or "UNIQUE(user_id, asset_id)," in table_sql


def migrate():
    db_path = get_db_path()
    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = OFF;")  # tắt tạm để rebuild bảng an toàn

    try:
        if column_unique_is_correct(conn):
            print("✅ Bảng user_downloads đã đúng cấu trúc UNIQUE(user_id, asset_id). Không cần migrate.")
            return

        cursor = conn.cursor()

        print("→ Đang dọn các dòng dupe cũ (giữ dòng downloaded_at mới nhất cho mỗi user+asset)...")
        cursor.execute('''
            DELETE FROM user_downloads
            WHERE id NOT IN (
                SELECT MAX(id) FROM user_downloads
                GROUP BY user_id, asset_id
            )
        ''')
        deleted = cursor.rowcount
        print(f"  Đã xóa {deleted} dòng dupe.")

        print("→ Đang build lại bảng user_downloads với UNIQUE(user_id, asset_id) mới...")
        cursor.execute('''
            CREATE TABLE user_downloads_new (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id         INTEGER,
                asset_id        INTEGER,
                format_selected VARCHAR(20) NOT NULL
                                CHECK (format_selected IN ('144p','240p','360p','480p','720p','1080p','audio','thumbnail')),
                download_status VARCHAR(20) DEFAULT 'PENDING'
                                CHECK(download_status IN ('PENDING','SUCCESS','FAILED')),
                downloaded_at   TIMESTAMP DEFAULT (datetime('now','localtime')),
                UNIQUE (user_id, asset_id),
                FOREIGN KEY (user_id)  REFERENCES users(id)   ON DELETE CASCADE,
                FOREIGN KEY (asset_id) REFERENCES media_assets(id) ON DELETE CASCADE
            )
        ''')
        cursor.execute('''
            INSERT INTO user_downloads_new (id, user_id, asset_id, format_selected, download_status, downloaded_at)
            SELECT id, user_id, asset_id, format_selected, download_status, downloaded_at FROM user_downloads
        ''')
        cursor.execute('DROP TABLE user_downloads')
        cursor.execute('ALTER TABLE user_downloads_new RENAME TO user_downloads')
        cursor.execute('CREATE INDEX IF NOT EXISTS idx_user_downloads_user ON user_downloads(user_id);')

        conn.commit()
        print("✅ Migrate hoàn tất. Bảng user_downloads giờ chỉ cho phép 1 dòng / asset / user.")
    finally:
        conn.execute("PRAGMA foreign_keys = ON;")
        conn.close()


if __name__ == '__main__':
    migrate()