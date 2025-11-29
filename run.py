#!/usr/bin/env python3
"""
Strava GO NUTS - Entry point for running from source

Run this script to start the application:
    python run.py
"""

import sys
import os

# Add current directory to path for imports
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# Fix SSL certificate verification for PyInstaller executables
if getattr(sys, 'frozen', False):
    # Running as PyInstaller executable
    import certifi
    os.environ['SSL_CERT_FILE'] = certifi.where()
    os.environ['REQUESTS_CA_BUNDLE'] = certifi.where()

from stravagonuts import create_app
from stravagonuts.database import init_database, REGIONS_DB
from stravagonuts.region_database_init import initialize_region_database
import logging
import threading
import webbrowser
import time


def download_regions_db():
    """Download regions.db if not present."""
    if os.path.exists(REGIONS_DB):
        return True

    print("\n" + "="*60)
    print("FIRST RUN DETECTED")
    print("="*60)
    print("\nDownloading region database (~144MB)")
    print("This is a one-time download that may take a few minutes...\n")

    # GitHub release asset URL
    RELEASE_URL = "https://github.com/jeroenbaas/stravagonuts/releases/latest/download/regions.db"

    # Ensure database directory exists
    db_dir = os.path.dirname(REGIONS_DB)
    os.makedirs(db_dir, exist_ok=True)

    try:
        import requests
        response = requests.get(RELEASE_URL, stream=True)
        response.raise_for_status()

        total_size = int(response.headers.get('content-length', 0))
        downloaded = 0

        with open(REGIONS_DB, 'wb') as f:
            for chunk in response.iter_content(chunk_size=8192):
                f.write(chunk)
                downloaded += len(chunk)
                if total_size:
                    percent = (downloaded / total_size) * 100
                    mb_downloaded = downloaded / (1024 * 1024)
                    mb_total = total_size / (1024 * 1024)
                    print(f"\rDownloading: {percent:.1f}% ({mb_downloaded:.1f}/{mb_total:.1f} MB)", end='')

        print("\n[OK] Region database downloaded successfully")
        print("="*60 + "\n")
        return True

    except Exception as e:
        print(f"\n[FAIL] Failed to download regions database: {e}")
        print("\nPlease download manually from:")
        print(RELEASE_URL)
        print(f"\nand place it at: {REGIONS_DB}")
        return False


def open_browser():
    """Open browser after short delay."""
    time.sleep(2.5)  # Longer delay to ensure server is ready
    webbrowser.open("http://127.0.0.1:5000")


def main():
    """Initialize and run the application."""
    print("="*60)
    print("STRAVA GO NUTS - STARTUP")
    print("="*60)

    # Step 1: Download region database if needed
    print("\n[1/3] Checking region database...")
    if not download_regions_db():
        print("\n" + "="*60)
        print("ERROR: Cannot continue without regions database")
        print("="*60)
        return 1

    # Step 2: Initialize database schema
    print("\n[2/3] Initializing database schema...")
    init_database()
    print("  [OK] Database schema ready")

    # Step 3: Initialize region reference database
    print("\n[3/3] Initializing region reference database...")
    if not initialize_region_database():
        print("\n" + "="*60)
        print("ERROR: Failed to initialize region database")
        print("The application cannot start without region data.")
        print("="*60)
        return 1

    print("\n" + "="*60)
    print("STARTUP COMPLETE")
    print("="*60)
    print("\nStarting Strava GO NUTS web server...")
    print("Server will run at: http://127.0.0.1:5000")
    print("\nPress Ctrl+C to stop the server\n")

    # Suppress Flask request logging for /api/status to reduce console clutter
    log = logging.getLogger('werkzeug')
    log.setLevel(logging.ERROR)

    # Create Flask app
    try:
        app = create_app()
        print("[SERVER] Flask app created successfully")
    except Exception as e:
        print(f"[ERROR] Failed to create Flask app: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Open browser in background thread
    threading.Thread(target=open_browser, daemon=True).start()
    print("[SERVER] Browser will open in 2.5 seconds...")

    # Run Flask app with error handling (localhost only - no external connections)
    try:
        print("[SERVER] Starting Flask server on 127.0.0.1:5000...")
        app.run(host="127.0.0.1", port=5000, debug=False, use_reloader=False, threaded=True)
    except Exception as e:
        print(f"[ERROR] Flask server error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
