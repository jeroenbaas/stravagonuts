import sqlite3
import json
import os
import sys
from datetime import datetime
from contextlib import contextmanager


def get_user_data_dir():
    """Get platform-specific user data directory."""
    if sys.platform == 'win32':
        base = os.environ.get('APPDATA', os.path.expanduser('~'))
        return os.path.join(base, 'StravaGoNuts')
    elif sys.platform == 'darwin':
        return os.path.expanduser('~/Library/Application Support/StravaGoNuts')
    else:  # Linux and other Unix-like systems
        return os.path.expanduser('~/.local/share/StravaGoNuts')


def get_database_paths():
    """Get database paths, using user data directory for executables."""
    # Check if running as PyInstaller executable
    if getattr(sys, 'frozen', False):
        # Running as executable - use platform-specific user data directory
        user_data_dir = get_user_data_dir()
        db_dir = os.path.join(user_data_dir, 'databases')
        os.makedirs(db_dir, exist_ok=True)
        return (
            os.path.join(db_dir, 'regions.db'),
            os.path.join(db_dir, 'user.db')
        )
    else:
        # Running from source - use local databases directory
        db_dir = 'databases'
        os.makedirs(db_dir, exist_ok=True)
        return (
            os.path.join(db_dir, 'regions.db'),
            os.path.join(db_dir, 'user.db')
        )


# Database paths
REGIONS_DB, USER_DB = get_database_paths()


@contextmanager
def get_db():
    """Get database connection with both regions and user databases."""
    conn = sqlite3.connect(USER_DB)
    conn.row_factory = sqlite3.Row
    # Attach regions database for querying
    conn.execute(f"ATTACH DATABASE '{REGIONS_DB}' AS regions")
    try:
        yield conn
    finally:
        conn.close()


def init_database():
    """Initialize database schema."""
    with get_db() as conn:
        cursor = conn.cursor()

        # Settings table for client credentials and tokens
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS settings (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)

        # Activities table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activities (
                id INTEGER PRIMARY KEY,
                name TEXT,
                type TEXT,
                start_date TEXT,
                distance REAL,
                has_streams INTEGER DEFAULT 0,
                streams_fetched INTEGER DEFAULT 0,
                streams_data TEXT,
                created_at TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migrate existing database: add streams_fetched column if it doesn't exist
        try:
            cursor.execute("SELECT streams_fetched FROM activities LIMIT 1")
            # Column exists, but check if we need to fix existing data
            cursor.execute("SELECT COUNT(*) FROM activities WHERE has_streams = 1 AND streams_fetched = 0")
            count = cursor.fetchone()[0]
            if count > 0:
                print(f"Fixing {count} activities that have streams but not marked as fetched...")
                cursor.execute("UPDATE activities SET streams_fetched = 1 WHERE has_streams = 1")
                conn.commit()
        except:
            print("Adding streams_fetched column to activities table...")
            cursor.execute("ALTER TABLE activities ADD COLUMN streams_fetched INTEGER DEFAULT 0")
            # For existing activities: if they have streams, mark them as fetched
            cursor.execute("UPDATE activities SET streams_fetched = 1 WHERE has_streams = 1")
            conn.commit()
            print("Migrated existing activities with streams")

        # LAU regions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lau_regions (
                lau_id TEXT PRIMARY KEY,
                name TEXT,
                country_code TEXT,
                geometry TEXT,
                first_visited TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Activity-LAU mapping table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activity_lau (
                activity_id INTEGER,
                lau_id TEXT,
                PRIMARY KEY (activity_id, lau_id),
                FOREIGN KEY (activity_id) REFERENCES activities(id),
                FOREIGN KEY (lau_id) REFERENCES lau_regions(lau_id)
            )
        """)

        # NUTS regions table (all levels: 0, 1, 2, 3)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS nuts_regions (
                nuts_code TEXT PRIMARY KEY,
                name TEXT,
                level INTEGER,
                country_code TEXT,
                geometry TEXT,
                first_visited TEXT DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Migrate existing lau_regions table to add geometry column
        cursor.execute("PRAGMA table_info(lau_regions)")
        lau_columns = [col[1] for col in cursor.fetchall()]
        if 'geometry' not in lau_columns:
            print("Adding geometry column to lau_regions table...")
            cursor.execute("ALTER TABLE lau_regions ADD COLUMN geometry TEXT")
            conn.commit()

        # Migrate existing nuts_regions table to add geometry column
        cursor.execute("PRAGMA table_info(nuts_regions)")
        nuts_columns = [col[1] for col in cursor.fetchall()]
        if 'geometry' not in nuts_columns:
            print("Adding geometry column to nuts_regions table...")
            cursor.execute("ALTER TABLE nuts_regions ADD COLUMN geometry TEXT")
            conn.commit()

        # Activity-NUTS mapping table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS activity_nuts (
                activity_id INTEGER,
                nuts_code TEXT,
                PRIMARY KEY (activity_id, nuts_code),
                FOREIGN KEY (activity_id) REFERENCES activities(id),
                FOREIGN KEY (nuts_code) REFERENCES nuts_regions(nuts_code)
            )
        """)

        # LAU to NUTS mapping table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lau_nuts_mapping (
                lau_id TEXT PRIMARY KEY,
                nuts0_code TEXT,
                nuts1_code TEXT,
                nuts2_code TEXT,
                nuts3_code TEXT,
                FOREIGN KEY (lau_id) REFERENCES lau_regions(lau_id)
            )
        """)

        # Metadata table for tracking last sync
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS metadata (
                key TEXT PRIMARY KEY,
                value TEXT
            )
        """)

        # First visited tracking tables (user-specific data)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lau_first_visited (
                lau_id TEXT PRIMARY KEY,
                first_visited TEXT
            )
        """)

        cursor.execute("""
            CREATE TABLE IF NOT EXISTS nuts_first_visited (
                nuts_code TEXT PRIMARY KEY,
                first_visited TEXT
            )
        """)

        conn.commit()


def get_setting(key, default=None):
    """Get a setting value."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT value FROM settings WHERE key = ?", (key,))
        row = cursor.fetchone()
        return row["value"] if row else default


def set_setting(key, value):
    """Set a setting value."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO settings (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
        """, (key, value))
        conn.commit()


def is_configured():
    """Check if app is configured with Strava credentials."""
    client_id = get_setting("client_id")
    client_secret = get_setting("client_secret")
    access_token = get_setting("access_token")
    return all([client_id, client_secret, access_token])


def save_activity(activity_id, name, activity_type, start_date, distance):
    """Save or update an activity."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT INTO activities (id, name, type, start_date, distance)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                type = excluded.type,
                start_date = excluded.start_date,
                distance = excluded.distance
        """, (activity_id, name, activity_type, start_date, distance))
        conn.commit()


def save_activity_streams(activity_id, streams_data):
    """Save streams data for an activity."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE activities
            SET has_streams = 1, streams_fetched = 1, streams_data = ?
            WHERE id = ?
        """, (json.dumps(streams_data), activity_id))
        conn.commit()


def mark_activity_no_streams(activity_id):
    """Mark that we attempted to fetch streams but none are available."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            UPDATE activities
            SET streams_fetched = 1, has_streams = 0
            WHERE id = ?
        """, (activity_id,))
        conn.commit()


def get_activities_without_streams():
    """Get all activities that haven't been attempted for stream fetching yet."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, type, start_date, distance
            FROM activities
            WHERE streams_fetched = 0
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_all_activities_with_streams():
    """Get all activities that have streams data."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT id, name, type, start_date, distance, streams_data
            FROM activities
            WHERE has_streams = 1
        """)
        activities = []
        for row in cursor.fetchall():
            activity = dict(row)
            if activity["streams_data"]:
                activity["streams_data"] = json.loads(activity["streams_data"])
            activities.append(activity)
        return activities


def save_lau_region(lau_id, name, country_code):
    """Save a LAU region."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO regions.lau_regions (lau_id, name, country_code)
            VALUES (?, ?, ?)
        """, (lau_id, name, country_code))
        conn.commit()


def link_activity_lau(activity_id, lau_id):
    """Link an activity to a LAU region."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO activity_lau (activity_id, lau_id)
            VALUES (?, ?)
        """, (activity_id, lau_id))
        conn.commit()


def update_lau_first_visited_dates():
    """Update first_visited dates for all LAU regions based on earliest activity."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO lau_first_visited (lau_id, first_visited)
            SELECT activity_lau.lau_id, MIN(activities.start_date)
            FROM activity_lau
            JOIN activities ON activity_lau.activity_id = activities.id
            GROUP BY activity_lau.lau_id
        """)
        conn.commit()
        print(f"[DB] Updated first_visited dates for LAU regions")


def get_all_lau_regions():
    """Get all visited LAU regions (only those with activities)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT regions.lau_regions.lau_id, name, country_code,
                   lau_first_visited.first_visited,
                   COUNT(DISTINCT activity_id) as activity_count
            FROM regions.lau_regions
            INNER JOIN activity_lau ON regions.lau_regions.lau_id = activity_lau.lau_id
            LEFT JOIN lau_first_visited ON regions.lau_regions.lau_id = lau_first_visited.lau_id
            GROUP BY regions.lau_regions.lau_id
            ORDER BY lau_first_visited.first_visited DESC
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_activity_count():
    """Get total number of activities."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM activities")
        return cursor.fetchone()["count"]


def get_activities_with_streams_count():
    """Get number of activities with streams."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM activities WHERE has_streams = 1")
        return cursor.fetchone()["count"]


def get_activities_not_fetched_count():
    """Get number of activities where we haven't attempted to fetch streams yet."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("SELECT COUNT(*) as count FROM activities WHERE streams_fetched = 0")
        return cursor.fetchone()["count"]


def clear_all_data():
    """Clear all data from database (for complete reset)."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("DELETE FROM activity_lau")
        cursor.execute("DELETE FROM regions.lau_regions")
        cursor.execute("DELETE FROM activities")
        cursor.execute("DELETE FROM metadata")
        conn.commit()


def get_last_activity_date():
    """Get the date of the most recent activity."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT MAX(start_date) as last_date
            FROM activities
        """)
        row = cursor.fetchone()
        return row["last_date"] if row["last_date"] else None


# ==============================================================================
# NUTS Region Functions
# ==============================================================================

def save_nuts_region(nuts_code, name, level, country_code):
    """Save a NUTS region."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO regions.nuts_regions (nuts_code, name, level, country_code)
            VALUES (?, ?, ?, ?)
        """, (nuts_code, name, level, country_code))
        conn.commit()


def save_lau_nuts_mapping(lau_id, nuts0, nuts1, nuts2, nuts3):
    """Save LAU to NUTS mapping."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO regions.lau_nuts_mapping 
            (lau_id, nuts0_code, nuts1_code, nuts2_code, nuts3_code)
            VALUES (?, ?, ?, ?, ?)
        """, (lau_id, nuts0, nuts1, nuts2, nuts3))
        conn.commit()


def link_activity_nuts(activity_id, nuts_code):
    """Link an activity to a NUTS region."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR IGNORE INTO activity_nuts (activity_id, nuts_code)
            VALUES (?, ?)
        """, (activity_id, nuts_code))
        conn.commit()


def get_nuts_regions_by_level(level):
    """Get all visited NUTS regions at a specific level (0, 1, 2, or 3). Only returns regions with activities."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT regions.nuts_regions.nuts_code, name, country_code,
                   nuts_first_visited.first_visited,
                   COUNT(DISTINCT activity_id) as activity_count
            FROM regions.nuts_regions
            INNER JOIN activity_nuts ON regions.nuts_regions.nuts_code = activity_nuts.nuts_code
            LEFT JOIN nuts_first_visited ON regions.nuts_regions.nuts_code = nuts_first_visited.nuts_code
            WHERE level = ?
            GROUP BY regions.nuts_regions.nuts_code
            ORDER BY nuts_first_visited.first_visited DESC
        """, (level,))
        return [dict(row) for row in cursor.fetchall()]


def update_nuts_first_visited_dates():
    """Update first_visited dates for all NUTS regions based on earliest activity."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            INSERT OR REPLACE INTO nuts_first_visited (nuts_code, first_visited)
            SELECT activity_nuts.nuts_code, MIN(activities.start_date)
            FROM activity_nuts
            JOIN activities ON activity_nuts.activity_id = activities.id
            GROUP BY activity_nuts.nuts_code
        """)
        conn.commit()
        print(f"[DB] Updated first_visited dates for NUTS regions")


def get_visited_countries():
    """Get list of NUTS0 countries that have been visited."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT DISTINCT regions.nuts_regions.nuts_code, regions.nuts_regions.name
            FROM regions.nuts_regions
            INNER JOIN activity_nuts ON regions.nuts_regions.nuts_code = activity_nuts.nuts_code
            WHERE level = 0
            ORDER BY regions.nuts_regions.name
        """)
        return [dict(row) for row in cursor.fetchall()]


def get_all_lau_regions_filtered(country_code):
    """Get all visited LAU regions filtered by country."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT regions.lau_regions.lau_id, name, country_code,
                   lau_first_visited.first_visited,
                   COUNT(DISTINCT activity_id) as activity_count
            FROM regions.lau_regions
            INNER JOIN activity_lau ON regions.lau_regions.lau_id = activity_lau.lau_id
            LEFT JOIN lau_first_visited ON regions.lau_regions.lau_id = lau_first_visited.lau_id
            WHERE regions.lau_regions.country_code = ?
            GROUP BY regions.lau_regions.lau_id
            ORDER BY lau_first_visited.first_visited DESC
        """, (country_code,))
        return [dict(row) for row in cursor.fetchall()]


def get_nuts_regions_by_level_filtered(level, country_code):
    """Get all visited NUTS regions at a specific level filtered by country."""
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT regions.nuts_regions.nuts_code, name, country_code,
                   nuts_first_visited.first_visited,
                   COUNT(DISTINCT activity_id) as activity_count
            FROM regions.nuts_regions
            INNER JOIN activity_nuts ON regions.nuts_regions.nuts_code = activity_nuts.nuts_code
            LEFT JOIN nuts_first_visited ON regions.nuts_regions.nuts_code = nuts_first_visited.nuts_code
            WHERE level = ? AND regions.nuts_regions.country_code = ?
            GROUP BY regions.nuts_regions.nuts_code
            ORDER BY nuts_first_visited.first_visited DESC
        """, (level, country_code))
        return [dict(row) for row in cursor.fetchall()]


def get_total_regions_count(country_code=None):
    """Get total number of regions at each level, optionally filtered by country.

    Returns both visited and total counts for each level.
    """
    with get_db() as conn:
        cursor = conn.cursor()

        results = {}

        # LAU counts
        if country_code:
            # Visited LAU in country
            cursor.execute("""
                SELECT COUNT(DISTINCT regions.lau_regions.lau_id) as count
                FROM regions.lau_regions
                INNER JOIN activity_lau ON regions.lau_regions.lau_id = activity_lau.lau_id
                WHERE regions.lau_regions.country_code = ?
            """, (country_code,))
            visited_lau = cursor.fetchone()['count']

            # Total LAU in country
            cursor.execute("""
                SELECT COUNT(*) as count
                FROM regions.lau_regions
                WHERE country_code = ?
            """, (country_code,))
            total_lau = cursor.fetchone()['count']
        else:
            # All visited LAU
            cursor.execute("SELECT COUNT(DISTINCT lau_id) as count FROM activity_lau")
            visited_lau = cursor.fetchone()['count']

            # All LAU
            cursor.execute("SELECT COUNT(*) as count FROM regions.lau_regions")
            total_lau = cursor.fetchone()['count']

        results['lau'] = {'visited': visited_lau, 'total': total_lau}

        # NUTS counts for each level
        for level in [0, 1, 2, 3]:
            if country_code:
                # Visited NUTS in country
                cursor.execute("""
                    SELECT COUNT(DISTINCT regions.nuts_regions.nuts_code) as count
                    FROM regions.nuts_regions
                    INNER JOIN activity_nuts ON regions.nuts_regions.nuts_code = activity_nuts.nuts_code
                    WHERE regions.nuts_regions.level = ? AND regions.nuts_regions.country_code = ?
                """, (level, country_code))
                visited_nuts = cursor.fetchone()['count']

                # Total NUTS in country
                cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM regions.nuts_regions
                    WHERE level = ? AND country_code = ?
                """, (level, country_code))
                total_nuts = cursor.fetchone()['count']
            else:
                # All visited NUTS
                cursor.execute("""
                    SELECT COUNT(DISTINCT nuts_code) as count
                    FROM activity_nuts
                    WHERE nuts_code IN (SELECT nuts_code FROM regions.nuts_regions WHERE level = ?)
                """, (level,))
                visited_nuts = cursor.fetchone()['count']

                # All NUTS
                cursor.execute("""
                    SELECT COUNT(*) as count
                    FROM regions.nuts_regions
                    WHERE level = ?
                """, (level,))
                total_nuts = cursor.fetchone()['count']

            results[f'nuts{level}'] = {'visited': visited_nuts, 'total': total_nuts}

        return results
