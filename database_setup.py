import sqlite3
import os

def get_db_path():
    current_dir = os.path.dirname(os.path.abspath(__file__))
    return os.path.join(current_dir, 'directflow_master.db')

def get_connection():
    """Trả về kết nối DB đã bật foreign keys. Dùng chung toàn hệ thống."""
    conn = sqlite3.connect(get_db_path())
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON;")
    return conn

def create_master_database():
    db_path = get_db_path()
    with sqlite3.connect(db_path) as conn:
        cursor = conn.cursor()
        cursor.execute("PRAGMA foreign_keys = ON;")

        # 1. BẢNG NGƯỜI DÙNG (USERS)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS users (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                username        VARCHAR(50)  UNIQUE NOT NULL,
                password_hash   VARCHAR(255) NOT NULL,
                email           VARCHAR(100) UNIQUE,
                role            VARCHAR(20)  DEFAULT 'member'
                                CHECK(role IN ('guest','member','admin')),
                is_active       BOOLEAN      DEFAULT 1,
                last_login_at   TIMESTAMP,
                created_at      TIMESTAMP    DEFAULT (datetime('now','localtime'))
            )
        ''')

        # 2. BẢNG TÁC GIẢ (CREATORS)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS creators (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                channel_id   VARCHAR(100) NOT NULL,
                channel_name VARCHAR(100) NOT NULL,
                platform     VARCHAR(20)  NOT NULL
                             CHECK (platform IN ('youtube','tiktok','facebook','instagram')),
                UNIQUE (channel_id, platform)
            )
        ''')

        # 3. BẢNG KHO MEDIA (MEDIA ASSETS - Lưu trữ Metadata từ URL để SORT)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS media_assets (
                id               INTEGER PRIMARY KEY AUTOINCREMENT,
                creator_id       INTEGER,
                title            VARCHAR(255) NOT NULL,
                platform         VARCHAR(50)  NOT NULL,
                external_id      VARCHAR(100) NOT NULL,
                source_url       TEXT UNIQUE  NOT NULL,
                duration_seconds INTEGER,              -- Dùng để Sort theo thời lượng
                view_count       BIGINT,               -- Dùng để Sort theo lượt xem
                published_at     TIMESTAMP,            -- Dùng để Sort theo ngày phát hành
                UNIQUE (platform, external_id),
                FOREIGN KEY (creator_id) REFERENCES creators(id) ON DELETE SET NULL
            )
        ''')

        # 4. BẢNG BỘ NHỚ ĐỆM FILE (MEDIA CACHE)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS media_cache (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                asset_id      INTEGER NOT NULL,
                quality       VARCHAR(20) NOT NULL
                              CHECK (quality IN ('144p','240p','360p','480p','720p','1080p','audio','thumbnail')),
                download_url  TEXT NOT NULL,
                thumbnail_url TEXT,
                expires_at    TIMESTAMP NOT NULL,
                created_at    TIMESTAMP DEFAULT (datetime('now','localtime')),
                UNIQUE (asset_id, quality),
                FOREIGN KEY (asset_id) REFERENCES media_assets(id) ON DELETE CASCADE
            )
        ''')

        # 5. BẢNG LỊCH SỬ TẢI XUỐNG CÁ NHÂN (USER DOWNLOADS)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS user_downloads (
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

        # 6. BẢNG DANH SÁCH PHÁT (PLAYLISTS)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS playlists (
                id         INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id    INTEGER,
                name       VARCHAR(100) NOT NULL,
                is_public  BOOLEAN  DEFAULT 0,
                created_at TIMESTAMP DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
        ''')

        # 7. BẢNG CHI TIẾT DANH SÁCH PHÁT (PLAYLIST ITEMS)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS playlist_items (
                playlist_id INTEGER,
                asset_id    INTEGER,
                added_at    TIMESTAMP DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (playlist_id, asset_id),
                FOREIGN KEY (playlist_id) REFERENCES playlists(id)    ON DELETE CASCADE,
                FOREIGN KEY (asset_id)    REFERENCES media_assets(id) ON DELETE CASCADE
            )
        ''')

        # 8. BẢNG MỤC YÊU THÍCH (FAVORITES)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS favorites (
                user_id    INTEGER,
                asset_id   INTEGER,
                added_at   TIMESTAMP DEFAULT (datetime('now','localtime')),
                PRIMARY KEY (user_id, asset_id),
                FOREIGN KEY (user_id)  REFERENCES users(id) ON DELETE CASCADE,
                FOREIGN KEY (asset_id) REFERENCES media_assets(id) ON DELETE CASCADE
            )
        ''')

        # 9. BẢNG NHẬT KÝ HỆ THỐNG (SYSTEM LOGS)
        cursor.execute('''
            CREATE TABLE IF NOT EXISTS system_logs (
                id           INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id      INTEGER,
                asset_id     INTEGER,
                action_type  VARCHAR(50) NOT NULL,
                ip_address   VARCHAR(45),
                details      TEXT,
                processed_at TIMESTAMP DEFAULT (datetime('now','localtime')),
                FOREIGN KEY (user_id)  REFERENCES users(id)        ON DELETE SET NULL,
                FOREIGN KEY (asset_id) REFERENCES media_assets(id) ON DELETE SET NULL
            )
        ''')

        # BỘ CHỈ MỤC (INDEXES) - Tối ưu tốc độ cho Sort & Truy xuất cá nhân
        indexes = [
            "CREATE INDEX IF NOT EXISTS idx_media_assets_creator     ON media_assets(creator_id);",
            "CREATE INDEX IF NOT EXISTS idx_media_assets_sort_views  ON media_assets(view_count);",
            "CREATE INDEX IF NOT EXISTS idx_media_assets_sort_time   ON media_assets(duration_seconds);",
            "CREATE INDEX IF NOT EXISTS idx_media_cache_expires      ON media_cache(expires_at);",
            "CREATE INDEX IF NOT EXISTS idx_media_cache_asset        ON media_cache(asset_id);",
            "CREATE INDEX IF NOT EXISTS idx_system_logs_user          ON system_logs(user_id);",
            "CREATE INDEX IF NOT EXISTS idx_user_downloads_user       ON user_downloads(user_id);",
            "CREATE INDEX IF NOT EXISTS idx_playlists_user            ON playlists(user_id);",
            "CREATE INDEX IF NOT EXISTS idx_favorites_user            ON favorites(user_id);",
        ]
        for sql in indexes:
            cursor.execute(sql)

    print(f"Database sẵn sàng tại: {db_path}")

if __name__ == '__main__':
    create_master_database()