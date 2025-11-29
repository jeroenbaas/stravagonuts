#!/usr/bin/env python3
"""
Verify all imports are working correctly after package restructuring.
"""

import sys

def check_imports():
    print("Checking package imports...")
    
    try:
        # Check main package
        from stravagonuts import create_app
        print("[OK] stravagonuts.create_app")
        
        # Check all modules
        from stravagonuts import app
        print("[OK] stravagonuts.app")
        
        from stravagonuts import database
        print("[OK] stravagonuts.database")
        
        from stravagonuts import strava_service
        print("[OK] stravagonuts.strava_service")
        
        from stravagonuts import map_generator
        print("[OK] stravagonuts.map_generator")
        
        from stravagonuts import nuts_handler
        print("[OK] stravagonuts.nuts_handler")
        
        from stravagonuts import region_database_init
        print("[OK] stravagonuts.region_database_init")
        
        # Test app creation
        app_instance = create_app()
        print("[OK] App creation successful")
        
        print("\n[SUCCESS] All imports working correctly!")
        return 0
        
    except Exception as e:
        print(f"\n[FAIL] Import error: {e}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(check_imports())
