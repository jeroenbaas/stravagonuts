import requests
import time
import queue
import threading
from datetime import datetime
from .database import (
    get_setting, set_setting, save_activity, save_activity_streams,
    get_activities_without_streams, get_last_activity_date, mark_activity_no_streams
)


STRAVA_TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
ATHLETE_STATS_URL = "https://www.strava.com/api/v3/athletes/{id}/stats"
STREAMS_URL = "https://www.strava.com/api/v3/activities/{id}/streams?keys=latlng,time&key_by_type=true"


def refresh_access_token():
    """Refresh the Strava access token."""
    client_id = get_setting("client_id")
    client_secret = get_setting("client_secret")
    refresh_token = get_setting("refresh_token")

    response = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "grant_type": "refresh_token",
            "refresh_token": refresh_token,
        },
    )
    response.raise_for_status()
    data = response.json()

    set_setting("access_token", data["access_token"])
    set_setting("refresh_token", data["refresh_token"])

    return data["access_token"]


def get_headers():
    """Get authorization headers for Strava API."""
    access_token = get_setting("access_token")
    return {"Authorization": f"Bearer {access_token}"}


def get_total_activity_count():
    """Get total number of activities from Strava stats."""
    athlete_id = get_setting("athlete_id")
    if not athlete_id:
        return 0
    
    url = ATHLETE_STATS_URL.format(id=athlete_id)
    headers = get_headers()
    
    try:
        response = requests.get(url, headers=headers)
        if response.status_code == 401:
            refresh_access_token()
            headers = get_headers()
            response = requests.get(url, headers=headers)
            
        response.raise_for_status()
        stats = response.json()
        print(f"[STRAVA] Stats response: {stats}")
        
        total = (
            stats.get("all_ride_totals", {}).get("count", 0) +
            stats.get("all_run_totals", {}).get("count", 0) +
            stats.get("all_swim_totals", {}).get("count", 0)
        )
        return total
    except Exception as e:
        print(f"[STRAVA] Error getting stats: {e}")
        return 0


def fetch_and_store_activities_incremental(after_date=None, status_dict=None):
    """Fetch activities from Strava API and store them incrementally as we page."""
    print(f"[STRAVA] Fetching and storing activities incrementally...")
    if after_date:
        print(f"[STRAVA] Fetching activities after: {after_date}")
    else:
        print(f"[STRAVA] Fetching ALL activities")

    headers = get_headers()
    total_stored = 0
    page = 1
    per_page = 200

    params = {"page": page, "per_page": per_page}
    if after_date:
        # Convert to Unix timestamp
        after_timestamp = int(datetime.fromisoformat(after_date.replace("Z", "+00:00")).timestamp())
        params["after"] = after_timestamp
        print(f"[STRAVA] Using timestamp filter: {after_timestamp}")

    while True:
        try:
            print(f"[STRAVA] Requesting page {page}...")

            # Update status if provided
            if status_dict is not None:
                status_dict["message"] = f"Fetching page {page} from Strava..."
                status_dict["progress"] = total_stored
                status_dict["total"] = 0  # Unknown total during fetching

            response = requests.get(ACTIVITIES_URL, headers=headers, params=params)

            if response.status_code == 401:
                # Token expired, refresh and retry
                print(f"[STRAVA] Token expired, refreshing...")
                refresh_access_token()
                headers = get_headers()
                response = requests.get(ACTIVITIES_URL, headers=headers, params=params)

            response.raise_for_status()
            activities = response.json()
            print(f"[STRAVA] Received {len(activities)} activities on page {page}")

            if not activities:
                break

            # Save this page to database immediately
            print(f"[STRAVA] Saving page {page} to database...")
            for activity in activities:
                save_activity(
                    activity_id=activity["id"],
                    name=activity.get("name", "Untitled"),
                    activity_type=activity.get("type", "Unknown"),
                    start_date=activity.get("start_date"),
                    distance=activity.get("distance", 0),
                )
                total_stored += 1

            # Update status with current count
            if status_dict is not None:
                status_dict["progress"] = total_stored
                status_dict["total"] = 0  # Still unknown
                status_dict["message"] = f"Fetched and stored {total_stored} activities (page {page})..."

            if len(activities) < per_page:
                break

            page += 1
            params["page"] = page
            time.sleep(0.1)

        except Exception as e:
            print(f"[STRAVA] ERROR fetching activities: {e}")
            print(f"[STRAVA] Saved {total_stored} activities before error")
            break

    print(f"[STRAVA] Total activities fetched and stored: {total_stored}")
    return total_stored


def fetch_and_store_activities(status_dict, fetch_all=False):
    """Fetch activities from Strava and store in database incrementally."""
    print(f"[APP] fetch_and_store_activities called (fetch_all={fetch_all})")
    status_dict["stage"] = "Fetching and storing activities"
    status_dict["progress"] = 0
    status_dict["total"] = 0

    # Determine if we need to fetch only new activities
    after_date = None if fetch_all else get_last_activity_date()
    print(f"[APP] Last activity date in DB: {after_date}")

    # Fetch and store incrementally (saves to DB as each page is fetched)
    total_count = fetch_and_store_activities_incremental(after_date, status_dict)

    print(f"[APP] Fetched and stored {total_count} activities")
    return total_count


def get_activity_streams(activity_id):
    """Download latlng streams for a single activity."""
    url = STREAMS_URL.format(id=activity_id)
    headers = get_headers()

    try:
        response = requests.get(url, headers=headers)

        if response.status_code == 401:
            refresh_access_token()
            headers = get_headers()
            response = requests.get(url, headers=headers)

        if response.status_code == 404:
            return None

        response.raise_for_status()
        return response.json()

    except Exception as e:
        print(f"Error fetching streams for activity {activity_id}: {e}")
        return None


    print(f"[APP] Processed {len(activities)} activity streams")
    return len(activities)


def fetch_and_process_parallel(status_dict, fetch_all=False):
    """
    Fetch activities and streams in parallel.
    Producer: Fetches activity pages.
    Consumer: Fetches streams for new activities.
    """
    print(f"[PARALLEL] Starting parallel fetch and process (fetch_all={fetch_all})")
    
    # Initialize status
    status_dict["stage"] = "Syncing with Strava"
    status_dict["total"] = get_total_activity_count()
    status_dict["progress"] = 0
    status_dict["current_locations"] = []  # List of {lat, lng} for frontend
    
    # Queue for activities needing streams
    activity_queue = queue.Queue()
    stop_event = threading.Event()
    
    # Track processed count for progress bar
    processed_count = 0
    total_fetched = 0
    
    def stream_consumer():
        nonlocal processed_count
        while not stop_event.is_set() or not activity_queue.empty():
            try:
                activity = activity_queue.get(timeout=1)
                
                # Fetch stream
                streams = get_activity_streams(activity["id"])
                
                if streams and "latlng" in streams:
                    save_activity_streams(activity["id"], streams)
                    
                    # Add start location to status for map animation
                    latlngs = streams["latlng"]["data"]
                    if latlngs:
                        start_loc = latlngs[0]
                        status_dict["current_locations"].append({
                            "id": activity["id"],
                            "lat": start_loc[0],
                            "lng": start_loc[1]
                        })
                        # Keep list small
                        if len(status_dict["current_locations"]) > 20:
                            status_dict["current_locations"].pop(0)
                else:
                    mark_activity_no_streams(activity["id"])
                
                processed_count += 1
                status_dict["progress"] = processed_count
                status_dict["message"] = f"Processed {processed_count} activities..."
                
                activity_queue.task_done()
                
            except queue.Empty:
                continue
            except Exception as e:
                print(f"[PARALLEL] Consumer error: {e}")
    
    # Start consumer thread
    consumer_thread = threading.Thread(target=stream_consumer, daemon=True)
    consumer_thread.start()
    
    # Producer: Fetch activities
    try:
        after_date = None if fetch_all else get_last_activity_date()
        headers = get_headers()
        page = 1
        per_page = 200
        params = {"page": page, "per_page": per_page}
        
        if after_date:
            after_timestamp = int(datetime.fromisoformat(after_date.replace("Z", "+00:00")).timestamp())
            params["after"] = after_timestamp
            
        while True:
            print(f"[PARALLEL] Fetching page {page}...")
            response = requests.get(ACTIVITIES_URL, headers=headers, params=params)
            
            if response.status_code == 401:
                refresh_access_token()
                headers = get_headers()
                response = requests.get(ACTIVITIES_URL, headers=headers, params=params)
                
            response.raise_for_status()
            activities = response.json()
            
            if not activities:
                break
                
            for activity in activities:
                # Save basic info
                save_activity(
                    activity_id=activity["id"],
                    name=activity.get("name", "Untitled"),
                    activity_type=activity.get("type", "Unknown"),
                    start_date=activity.get("start_date"),
                    distance=activity.get("distance", 0),
                )
                total_fetched += 1
                
                # Queue for stream fetching
                activity_queue.put(activity)
                
            if len(activities) < per_page:
                break
                
            page += 1
            params["page"] = page
            
    except Exception as e:
        print(f"[PARALLEL] Producer error: {e}")
        status_dict["message"] = f"Error: {str(e)}"
        
    # Signal consumer to stop when queue is empty
    stop_event.set()
    consumer_thread.join()
    
    print(f"[PARALLEL] Finished. Fetched: {total_fetched}, Processed: {processed_count}")
    return processed_count
