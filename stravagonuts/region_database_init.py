"""
Initialize the complete region database (LAU and NUTS).
This runs on app startup to ensure all reference data is available.
"""

import os
import sqlite3
from contextlib import contextmanager
from .database import REGIONS_DB

@contextmanager
def get_regions_db():
    """Get connection to regions database for initialization."""
    os.makedirs(os.path.dirname(REGIONS_DB), exist_ok=True)
    conn = sqlite3.connect(REGIONS_DB)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()

from .nuts_handler import parse_nuts_mapping, load_nuts_shapefile, filter_nuts_by_level
from .map_generator import ensure_lau_shapefile
import geopandas as gpd


def create_regions_schema():
    """Create the schema for regions database."""
    with get_regions_db() as conn:
        cursor = conn.cursor()

        # LAU regions table
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS lau_regions (
                lau_id TEXT PRIMARY KEY,
                name TEXT,
                country_code TEXT,
                geometry TEXT
            )
        """)

        # NUTS regions table (all levels: 0, 1, 2, 3)
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS nuts_regions (
                nuts_code TEXT PRIMARY KEY,
                name TEXT,
                level INTEGER,
                country_code TEXT,
                geometry TEXT
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

        conn.commit()


def check_region_database_status():
    """Check if region database is initialized."""
    with get_regions_db() as conn:
        cursor = conn.cursor()

        try:
            # Count LAU regions
            cursor.execute("SELECT COUNT(*) FROM lau_regions")
            lau_count = cursor.fetchone()[0]

            # Count NUTS regions by level
            nuts_counts = {}
            for level in [0, 1, 2, 3]:
                cursor.execute("SELECT COUNT(*) FROM nuts_regions WHERE level = ?", (level,))
                nuts_counts[level] = cursor.fetchone()[0]

            # Count LAU-NUTS mappings
            cursor.execute("SELECT COUNT(*) FROM lau_nuts_mapping")
            mapping_count = cursor.fetchone()[0]

            return {
                'lau_count': lau_count,
                'nuts_counts': nuts_counts,
                'mapping_count': mapping_count,
                'is_initialized': lau_count > 0 and all(c > 0 for c in nuts_counts.values())
            }
        except sqlite3.OperationalError:
            # Tables don't exist yet
            return {
                'lau_count': 0,
                'nuts_counts': {0: 0, 1: 0, 2: 0, 3: 0},
                'mapping_count': 0,
                'is_initialized': False
            }


def initialize_region_database(force=False):
    """
    Initialize the complete region reference database.

    This loads ALL regions (not just visited ones) into the database:
    - All LAU regions from shapefile
    - All NUTS regions at all levels from shapefile
    - LAU to NUTS mappings from Excel

    Args:
        force: If True, re-initialize even if already initialized
    """

    # Create schema first
    create_regions_schema()

    status = check_region_database_status()

    if status['is_initialized'] and not force:
        print("[REGIONS] Region database already initialized:")
        print(f"  - LAU regions: {status['lau_count']}")
        for level, count in status['nuts_counts'].items():
            print(f"  - NUTS{level} regions: {count}")
        print(f"  - LAU-NUTS mappings: {status['mapping_count']}")
        return True

    print("\n" + "="*60)
    print("INITIALIZING REGION REFERENCE DATABASE")
    print("="*60)

    try:
        # Step 1: Load ALL LAU regions
        print("\n[1/4] Loading LAU regions...")
        load_all_lau_regions()

        # Step 2: Load ALL NUTS regions
        print("\n[2/4] Loading NUTS regions...")
        load_all_nuts_regions()

        # Step 3: Create LAU-NUTS mappings
        print("\n[3/4] Creating LAU-NUTS mappings...")
        create_lau_nuts_mappings()

        # Step 4: Verify
        print("\n[4/4] Verifying data...")
        status = check_region_database_status()

        if not status['is_initialized']:
            raise RuntimeError("Region database initialization failed - data is incomplete")

        print("\n" + "="*60)
        print("REGION DATABASE INITIALIZED SUCCESSFULLY")
        print("="*60)
        print(f"LAU regions: {status['lau_count']}")
        for level, count in status['nuts_counts'].items():
            print(f"NUTS{level} regions: {count}")
        print(f"LAU-NUTS mappings: {status['mapping_count']}")
        print("="*60 + "\n")

        return True

    except Exception as e:
        print(f"\n[ERROR] Failed to initialize region database: {e}")
        import traceback
        traceback.print_exc()
        return False


def load_all_lau_regions():
    """Load all LAU regions from shapefile into database."""

    # Load LAU shapefile
    shp_path = ensure_lau_shapefile()
    lau_gdf = gpd.read_file(shp_path)
    lau_gdf = lau_gdf.rename(columns={"GISCO_ID": "LAU_ID", "LAU_NAME": "NAME_LATN"})

    print(f"  Loading {len(lau_gdf)} LAU regions from shapefile...")

    # Insert all LAU regions with geometry
    with get_regions_db() as conn:
        cursor = conn.cursor()

        for idx, row in lau_gdf.iterrows():
            # Convert geometry to WKT for storage
            geometry_wkt = row['geometry'].wkt if row['geometry'] else None

            cursor.execute("""
                INSERT OR IGNORE INTO lau_regions (lau_id, name, country_code, geometry)
                VALUES (?, ?, ?, ?)
            """, (
                row['LAU_ID'],
                row.get('NAME_LATN', row['LAU_ID']),
                row['LAU_ID'][:2] if '_' in row['LAU_ID'] else row.get('CNTR_CODE', ''),
                geometry_wkt
            ))

        conn.commit()

    print(f"  [OK] Loaded {len(lau_gdf)} LAU regions")


def load_all_nuts_regions():
    """Load all NUTS regions from shapefile into database."""

    # Load NUTS shapefile
    nuts_gdf = load_nuts_shapefile()

    print(f"  Loading {len(nuts_gdf)} NUTS regions from shapefile...")

    # Insert all NUTS regions with geometry
    with get_regions_db() as conn:
        cursor = conn.cursor()

        for idx, row in nuts_gdf.iterrows():
            level = row.get('LEVL_CODE', len(row['NUTS_CODE']) - 2)
            # Convert geometry to WKT for storage
            geometry_wkt = row['geometry'].wkt if row['geometry'] else None

            cursor.execute("""
                INSERT OR IGNORE INTO nuts_regions (nuts_code, name, level, country_code, geometry)
                VALUES (?, ?, ?, ?, ?)
            """, (
                row['NUTS_CODE'],
                row.get('NUTS_NAME', row.get('NAME_LATN', row['NUTS_CODE'])),
                level,
                row.get('CNTR_CODE', row['NUTS_CODE'][:2]),
                geometry_wkt
            ))

        conn.commit()

    # Count by level
    with get_regions_db() as conn:
        cursor = conn.cursor()
        for level in [0, 1, 2, 3]:
            cursor.execute("SELECT COUNT(*) FROM nuts_regions WHERE level = ?", (level,))
            count = cursor.fetchone()[0]
            print(f"  [OK] Loaded {count} NUTS{level} regions")


def create_lau_nuts_mappings():
    """Create LAU to NUTS mappings from Excel file."""

    # Parse Excel mapping
    lau_nuts_df = parse_nuts_mapping()

    print(f"  Creating {len(lau_nuts_df)} LAU-NUTS mappings...")

    # Insert mappings
    with get_regions_db() as conn:
        cursor = conn.cursor()

        for idx, row in lau_nuts_df.iterrows():
            cursor.execute("""
                INSERT OR REPLACE INTO lau_nuts_mapping
                (lau_id, nuts0_code, nuts1_code, nuts2_code, nuts3_code)
                VALUES (?, ?, ?, ?, ?)
            """, (
                row['LAU_CODE'],
                row['NUTS0_CODE'],
                row['NUTS1_CODE'],
                row['NUTS2_CODE'],
                row['NUTS3_CODE']
            ))

        conn.commit()

    print(f"  [OK] Created {len(lau_nuts_df)} LAU-NUTS mappings")
