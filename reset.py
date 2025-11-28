#!/usr/bin/env python3
"""
Reset script for Strava GO NUTS
Provides options to reset different types of data.
"""

import os
import shutil
import sys
import sqlite3


def show_menu():
    """Display reset options menu."""
    print("=" * 60)
    print("  STRAVA GO NUTS MAPPER - RESET TOOL")
    print("=" * 60)
    print("\nWhat would you like to reset?\n")
    print("  1. All data (complete reset)")
    print("  2. User data (activities, auth, keep region database)")
    print("  3. Map data (generated maps only)")
    print("  4. Region database (LAU/NUTS data, will reload on next start)")
    print("  5. Cancel")
    print("\n" + "=" * 60)


def confirm_action(action_desc):
    """Ask user to confirm the action."""
    response = input(f"\nAre you sure you want to {action_desc}? (yes/no): ").strip().lower()
    return response in ['yes', 'y']


def delete_file(filepath, description):
    """Delete a file if it exists."""
    if os.path.exists(filepath):
        try:
            os.remove(filepath)
            print(f"✓ Deleted {description}: {filepath}")
            return True
        except Exception as e:
            print(f"✗ Failed to delete {description}: {e}")
            return False
    else:
        print(f"- {description} not found (already clean)")
        return True


def delete_directory(dirpath, description):
    """Delete a directory if it exists."""
    if os.path.exists(dirpath):
        try:
            shutil.rmtree(dirpath)
            print(f"✓ Deleted {description}: {dirpath}")
            return True
        except Exception as e:
            print(f"✗ Failed to delete {description}: {e}")
            return False
    else:
        print(f"- {description} not found (already clean)")
        return True


def clear_user_data_from_db():
    """Clear activities and auth data but keep region database."""
    db_path = "strava_lau.db"
    if not os.path.exists(db_path):
        print("- Database not found (already clean)")
        return True

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        # Clear user data tables
        print("  Clearing activities...")
        cursor.execute("DELETE FROM activities")

        print("  Clearing activity-region links...")
        cursor.execute("DELETE FROM activity_lau")
        cursor.execute("DELETE FROM activity_nuts")

        print("  Clearing authentication...")
        cursor.execute("DELETE FROM settings")
        cursor.execute("DELETE FROM metadata")

        print("  Resetting first_visited dates...")
        cursor.execute("UPDATE lau_regions SET first_visited = NULL")
        cursor.execute("UPDATE nuts_regions SET first_visited = NULL")

        conn.commit()
        conn.close()

        print("✓ Cleared user data from database (region data preserved)")
        return True
    except Exception as e:
        print(f"✗ Failed to clear user data: {e}")
        return False


def clear_region_data_from_db():
    """Clear region database tables (LAU, NUTS, mappings)."""
    db_path = "strava_lau.db"
    if not os.path.exists(db_path):
        print("- Database not found (already clean)")
        return True

    try:
        conn = sqlite3.connect(db_path)
        cursor = conn.cursor()

        print("  Clearing LAU regions...")
        cursor.execute("DELETE FROM lau_regions")

        print("  Clearing NUTS regions...")
        cursor.execute("DELETE FROM nuts_regions")

        print("  Clearing LAU-NUTS mappings...")
        cursor.execute("DELETE FROM lau_nuts_mapping")

        print("  Clearing activity-region links...")
        cursor.execute("DELETE FROM activity_lau")
        cursor.execute("DELETE FROM activity_nuts")

        conn.commit()
        conn.close()

        print("✓ Cleared region database (will reload on next startup)")
        return True
    except Exception as e:
        print(f"✗ Failed to clear region data: {e}")
        return False


def reset_all():
    """Complete reset - delete everything."""
    print("\n" + "=" * 60)
    print("COMPLETE RESET - This will DELETE:")
    print("  - All authentication credentials")
    print("  - All stored activities")
    print("  - All region data (LAU/NUTS)")
    print("  - Database file")
    print("  - Generated maps")
    print("  - Cached shapefiles")
    print("=" * 60)

    if not confirm_action("reset ALL data"):
        return False

    print("\nStarting complete reset...\n")
    success = True

    # Delete database
    success &= delete_file("strava_lau.db", "SQLite database")

    # Delete generated maps
    success &= delete_file("static/map.png", "Static map")
    success &= delete_file("static/map.html", "Interactive map (default)")
    success &= delete_file("static/map_lau.html", "LAU map")
    success &= delete_file("static/map_0.html", "NUTS 0 map")
    success &= delete_file("static/map_1.html", "NUTS 1 map")
    success &= delete_file("static/map_2.html", "NUTS 2 map")
    success &= delete_file("static/map_3.html", "NUTS 3 map")

    # Delete cached data
    success &= delete_directory("lau_data", "Cached LAU shapefile")
    success &= delete_directory("nuts_data", "Cached NUTS data")

    return success


def reset_user_data():
    """Reset user data only - keep region database."""
    print("\n" + "=" * 60)
    print("USER DATA RESET - This will DELETE:")
    print("  - All authentication credentials")
    print("  - All stored activities")
    print("  - Activity-region links")
    print("\nThis will KEEP:")
    print("  - Region database (LAU/NUTS)")
    print("  - Cached shapefiles")
    print("=" * 60)

    if not confirm_action("reset user data"):
        return False

    print("\nResetting user data...\n")
    success = True

    # Clear user data from database
    success &= clear_user_data_from_db()

    # Delete generated maps (need to regenerate)
    success &= delete_file("static/map.png", "Static map")
    success &= delete_file("static/map.html", "Interactive map (default)")
    success &= delete_file("static/map_lau.html", "LAU map")
    success &= delete_file("static/map_0.html", "NUTS 0 map")
    success &= delete_file("static/map_1.html", "NUTS 1 map")
    success &= delete_file("static/map_2.html", "NUTS 2 map")
    success &= delete_file("static/map_3.html", "NUTS 3 map")

    return success


def reset_map_data():
    """Reset generated maps only."""
    print("\n" + "=" * 60)
    print("MAP DATA RESET - This will DELETE:")
    print("  - All generated map files")
    print("\nThis will KEEP:")
    print("  - Database (activities, regions, auth)")
    print("  - Cached shapefiles")
    print("=" * 60)

    if not confirm_action("delete all maps"):
        return False

    print("\nDeleting maps...\n")
    success = True

    # Delete generated maps
    success &= delete_file("static/map.png", "Static map")
    success &= delete_file("static/map.html", "Interactive map (default)")
    success &= delete_file("static/map_lau.html", "LAU map")
    success &= delete_file("static/map_0.html", "NUTS 0 map")
    success &= delete_file("static/map_1.html", "NUTS 1 map")
    success &= delete_file("static/map_2.html", "NUTS 2 map")
    success &= delete_file("static/map_3.html", "NUTS 3 map")

    return success


def reset_region_database():
    """Reset region database - will reload on next start."""
    print("\n" + "=" * 60)
    print("REGION DATABASE RESET - This will DELETE:")
    print("  - All LAU regions")
    print("  - All NUTS regions")
    print("  - LAU-NUTS mappings")
    print("  - Activity-region links")
    print("  - Cached shapefiles")
    print("\nThis will KEEP:")
    print("  - Activities and authentication")
    print("\nRegion data will be reloaded on next startup.")
    print("=" * 60)

    if not confirm_action("reset region database"):
        return False

    print("\nResetting region database...\n")
    success = True

    # Clear region data from database
    success &= clear_region_data_from_db()

    # Delete cached shapefiles (will redownload)
    success &= delete_directory("lau_data", "Cached LAU shapefile")
    success &= delete_directory("nuts_data", "Cached NUTS data")

    # Delete maps (need to regenerate)
    success &= delete_file("static/map.png", "Static map")
    success &= delete_file("static/map.html", "Interactive map (default)")
    success &= delete_file("static/map_lau.html", "LAU map")
    success &= delete_file("static/map_0.html", "NUTS 0 map")
    success &= delete_file("static/map_1.html", "NUTS 1 map")
    success &= delete_file("static/map_2.html", "NUTS 2 map")
    success &= delete_file("static/map_3.html", "NUTS 3 map")

    return success


def main():
    """Main reset function with menu."""
    show_menu()

    choice = input("Enter your choice (1-5): ").strip()

    if choice == '1':
        success = reset_all()
    elif choice == '2':
        success = reset_user_data()
    elif choice == '3':
        success = reset_map_data()
    elif choice == '4':
        success = reset_region_database()
    elif choice == '5':
        print("\nReset cancelled.")
        sys.exit(0)
    else:
        print("\n✗ Invalid choice. Exiting.")
        sys.exit(1)

    print("\n" + "=" * 60)
    if success:
        print("✓ Reset complete!")
        print("\nYou can now run the app:")
        print("  python app.py")
    else:
        print("⚠ Reset completed with some errors (see above)")
        print("  Some files may need to be manually deleted")
    print("=" * 60)


if __name__ == "__main__":
    main()
