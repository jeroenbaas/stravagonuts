import sys
import os

# Add current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from stravagonuts.strava_service import get_total_activity_count

print("Checking Strava stats...")
count = get_total_activity_count()
print(f"Total count: {count}")
