import os
import json
import requests
from flask import Flask, render_template, request, jsonify, redirect, url_for, session

from .database import (
    init_database, is_configured, get_setting, set_setting,
    get_activity_count, get_all_lau_regions, get_activities_with_streams_count,
    get_activities_not_fetched_count, get_nuts_regions_by_level, clear_activities
)
from .strava_service import fetch_and_store_activities, process_activity_streams
from .map_generator import generate_map


# Module-level app instance for routes
app = Flask(__name__)
app.secret_key = os.urandom(24)

STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"

# Global variable to track processing status
processing_status = {
    "is_processing": False,
    "stage": "",
    "progress": 0,
    "total": 0,
    "message": ""
}


def create_app():
    """Create and configure the Flask application."""
    return app


@app.route("/")
def index():
    """Landing page - setup or map view."""
    if not is_configured():
        return redirect(url_for("setup"))

    activity_count = get_activity_count()
    activities_with_streams = get_activities_with_streams_count()
    activities_not_fetched = get_activities_not_fetched_count()
    lau_regions = get_all_lau_regions()

    # Get athlete information
    athlete_firstname = get_setting("athlete_firstname", "")
    athlete_lastname = get_setting("athlete_lastname", "")
    athlete_username = get_setting("athlete_username", "")
    athlete_id = get_setting("athlete_id", "")

    athlete_name = f"{athlete_firstname} {athlete_lastname}".strip() or athlete_username or f"Athlete {athlete_id}"

    # Check if maps are missing but we have activities
    maps_missing = False
    if activities_with_streams > 0:
        # Check if any map files exist
        map_files = [
            "static/map_lau.html",
            "static/map_0.html",
            "static/map_1.html",
            "static/map_2.html",
            "static/map_3.html"
        ]
        maps_exist = any(os.path.exists(f) for f in map_files)
        maps_missing = not maps_exist

    # Check if we should auto-start processing
    # Auto-process if:
    # 1. Activities need GPS fetch attempt, OR
    # 2. Maps are missing but we have activities with GPS data
    should_auto_process = (
        (activities_not_fetched > 0 or maps_missing) and
        not processing_status["is_processing"]
    )

    if should_auto_process:
        if activities_not_fetched > 0:
            print(f"[INDEX] Auto-processing will be triggered: {activities_not_fetched} activities need GPS fetch attempt")
        if maps_missing:
            print(f"[INDEX] Auto-processing will be triggered: Maps missing but {activities_with_streams} activities with GPS data found")

    return render_template(
        "index.html",
        activity_count=activity_count,
        activities_with_streams=activities_with_streams,
        activities_not_fetched=activities_not_fetched,
        lau_count=len(lau_regions),
        has_data=activity_count > 0,
        athlete_name=athlete_name,
        athlete_id=athlete_id,
        should_auto_process=should_auto_process
    )


@app.route("/setup")
def setup():
    """Initial setup page for Strava credentials."""
    if is_configured():
        return redirect(url_for("index"))
    return render_template("setup.html")


@app.route("/api/save-credentials", methods=["POST"])
def save_credentials():
    """Save Strava client credentials."""
    data = request.json
    client_id = data.get("client_id")
    client_secret = data.get("client_secret")

    if not client_id or not client_secret:
        return jsonify({"error": "Missing credentials"}), 400

    set_setting("client_id", client_id)
    set_setting("client_secret", client_secret)

    return jsonify({"success": True})


@app.route("/oauth/authorize")
def oauth_authorize():
    """Redirect to Strava OAuth authorization."""
    client_id = get_setting("client_id")

    if not client_id:
        return redirect(url_for("setup"))

    redirect_uri = request.url_root.rstrip("/") + url_for("oauth_callback")

    auth_url = (
        f"{STRAVA_AUTH_URL}?"
        f"client_id={client_id}&"
        f"response_type=code&"
        f"redirect_uri={redirect_uri}&"
        f"approval_prompt=force&"
        f"scope=read,activity:read_all"
    )

    return redirect(auth_url)


@app.route("/oauth/callback")
def oauth_callback():
    """Handle OAuth callback from Strava."""
    code = request.args.get("code")

    if not code:
        return "Authorization failed: no code received", 400

    client_id = get_setting("client_id")
    client_secret = get_setting("client_secret")
    redirect_uri = request.url_root.rstrip("/") + url_for("oauth_callback")

    # Exchange code for tokens
    try:
        response = requests.post(
            STRAVA_TOKEN_URL,
            data={
                "client_id": client_id,
                "client_secret": client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": redirect_uri,
            },
        )
        response.raise_for_status()
        token_data = response.json()

        set_setting("access_token", token_data["access_token"])
        set_setting("refresh_token", token_data["refresh_token"])

        # Store athlete information
        if "athlete" in token_data:
            athlete = token_data["athlete"]
            set_setting("athlete_id", str(athlete.get("id", "")))
            set_setting("athlete_firstname", athlete.get("firstname", ""))
            set_setting("athlete_lastname", athlete.get("lastname", ""))
            set_setting("athlete_username", athlete.get("username", ""))

        return redirect(url_for("index"))

    except Exception as e:
        return f"Token exchange failed: {str(e)}", 500


@app.route("/api/status")
def get_status():
    """Get current processing status."""
    return jsonify(processing_status)


@app.route("/api/update", methods=["POST"])
def update_activities():
    """Update with new activities since last sync."""
    global processing_status

    print("\n" + "="*60)
    print("[UPDATE] Update endpoint called")
    print("="*60)

    if processing_status["is_processing"]:
        print("[UPDATE] Already processing, returning error")
        return jsonify({"error": "Already processing"}), 400

    def process():
        global processing_status
        try:
            print("[UPDATE] Starting processing thread...")
            processing_status["is_processing"] = True
            processing_status["stage"] = "Fetching activities"
            processing_status["progress"] = 0
            processing_status["total"] = 0

            # Fetch and store activities
            print("[UPDATE] Calling fetch_and_store_activities...")
            fetch_and_store_activities(processing_status)

            # Process streams
            print("[UPDATE] Calling process_activity_streams...")
            process_activity_streams(processing_status)

            # Generate map
            print("[UPDATE] Calling generate_map...")
            processing_status["stage"] = "Generating map"
            processing_status["progress"] = 0
            processing_status["total"] = 1
            processing_status["message"] = "Creating map visualization..."
            generate_map(processing_status)

            processing_status["stage"] = "Complete"
            processing_status["message"] = "Update complete!"
            processing_status["progress"] = 1
            processing_status["total"] = 1
            print("[UPDATE] Processing complete!")

        except Exception as e:
            print(f"[UPDATE] ERROR: {e}")
            import traceback
            traceback.print_exc()
            processing_status["stage"] = "Error"
            processing_status["message"] = str(e)

        finally:
            processing_status["is_processing"] = False

    import threading
    thread = threading.Thread(target=process)
    thread.start()
    print("[UPDATE] Background thread started")

    return jsonify({"success": True})


@app.route("/api/reset", methods=["POST"])
def reset_data():
    """Complete reset - clear all data and reload everything."""
    global processing_status

    print("\n" + "="*60)
    print("[RESET] Reset endpoint called")
    print("="*60)

    if processing_status["is_processing"]:
        print("[RESET] Already processing, returning error")
        return jsonify({"error": "Already processing"}), 400

    def process():
        global processing_status
        try:
            from .database import clear_all_data

            print("[RESET] Starting processing thread...")
            processing_status["is_processing"] = True
            processing_status["stage"] = "Clearing data"
            processing_status["progress"] = 0

            # Clear all data
            print("[RESET] Clearing all data from database...")
            clear_all_data()

            # Fetch everything
            print("[RESET] Fetching all activities...")
            processing_status["stage"] = "Fetching all activities"
            fetch_and_store_activities(processing_status, fetch_all=True)

            # Process streams
            print("[RESET] Processing activity streams...")
            process_activity_streams(processing_status)

            # Generate map
            print("[RESET] Generating map...")
            processing_status["stage"] = "Generating map"
            processing_status["progress"] = 0
            processing_status["total"] = 1
            processing_status["message"] = "Creating map visualization..."
            generate_map(processing_status)

            processing_status["stage"] = "Complete"
            processing_status["message"] = "Reset complete!"
            processing_status["progress"] = 1
            processing_status["total"] = 1
            print("[RESET] Processing complete!")

        except Exception as e:
            print(f"[RESET] ERROR: {e}")
            import traceback
            traceback.print_exc()
            processing_status["stage"] = "Error"
            processing_status["message"] = str(e)

        finally:
            processing_status["is_processing"] = False

    import threading
    thread = threading.Thread(target=process)
    thread.start()
    print("[RESET] Background thread started")

    return jsonify({"success": True})


@app.route("/api/reset-activities", methods=["POST"])
def reset_activities():
    """Reset activities only - clear activity data and re-download from Strava."""
    global processing_status

    print("\n" + "="*60)
    print("[RESET ACTIVITIES] Reset activities endpoint called")
    print("="*60)

    if processing_status["is_processing"]:
        print("[RESET ACTIVITIES] Already processing, returning error")
        return jsonify({"error": "Already processing"}), 400

    def process():
        global processing_status
        try:
            print("[RESET ACTIVITIES] Starting processing thread...")
            processing_status["is_processing"] = True
            processing_status["stage"] = "Clearing activities"
            processing_status["progress"] = 0

            # Clear only activity data
            print("[RESET ACTIVITIES] Clearing activity data from database...")
            clear_activities()

            # Fetch everything
            print("[RESET ACTIVITIES] Fetching all activities...")
            processing_status["stage"] = "Fetching all activities"
            fetch_and_store_activities(processing_status, fetch_all=True)

            # Process streams
            print("[RESET ACTIVITIES] Processing activity streams...")
            process_activity_streams(processing_status)

            # Generate map
            print("[RESET ACTIVITIES] Generating map...")
            processing_status["stage"] = "Generating map"
            processing_status["progress"] = 0
            processing_status["total"] = 1
            processing_status["message"] = "Creating map visualization..."
            generate_map(processing_status)

            processing_status["stage"] = "Complete"
            processing_status["message"] = "Activities reset complete!"
            processing_status["progress"] = 1
            processing_status["total"] = 1
            print("[RESET ACTIVITIES] Processing complete!")

        except Exception as e:
            print(f"[RESET ACTIVITIES] ERROR: {e}")
            import traceback
            traceback.print_exc()
            processing_status["stage"] = "Error"
            processing_status["message"] = str(e)

        finally:
            processing_status["is_processing"] = False

    import threading
    thread = threading.Thread(target=process)
    thread.start()
    print("[RESET ACTIVITIES] Background thread started")

    return jsonify({"success": True})


@app.route("/api/regions")
def get_regions():
    """Get all visited regions for a specific administrative level.

    Query params:
        level: 'lau' (default), '0', '1', '2', or '3'
        country: NUTS0 country code (optional filter)
    """
    level = request.args.get('level', 'lau').lower()
    country = request.args.get('country', '').upper()

    if level == 'lau':
        from .database import get_all_lau_regions_filtered
        regions = get_all_lau_regions_filtered(country) if country else get_all_lau_regions()
        # Normalize keys for frontend
        for r in regions:
            r['code'] = r.get('lau_id')
            r['region_name'] = r.get('name')
    else:
        try:
            level_int = int(level)
            if level_int not in [0, 1, 2, 3]:
                return jsonify({"error": "Invalid level. Must be 'lau', 0, 1, 2, or 3"}), 400

            from .database import get_nuts_regions_by_level_filtered
            regions = get_nuts_regions_by_level_filtered(level_int, country) if country else get_nuts_regions_by_level(level_int)
            # Normalize keys for frontend
            for r in regions:
                r['code'] = r.get('nuts_code')
                r['region_name'] = r.get('name')
        except ValueError:
            return jsonify({"error": "Invalid level parameter"}), 400

    return jsonify(regions)


@app.route("/api/countries")
def get_countries():
    """Get list of NUTS0 countries with activities."""
    from .database import get_visited_countries
    countries = get_visited_countries()
    return jsonify(countries)


@app.route("/api/totals")
def get_totals():
    """Get total region counts for all levels.

    Query params:
        country: NUTS0 country code (optional filter)
    """
    country = request.args.get('country', '').upper()

    from .database import get_total_regions_count
    totals = get_total_regions_count(country if country else None)
    return jsonify(totals)


@app.route("/static/map_<level>.html")
def serve_map(level):
    """Serve map HTML file, generating it if missing or if country filter applied."""
    country = request.args.get('country', '').upper()

    # Use absolute path relative to this file
    if country:
        # Country-filtered map - always generate on demand
        map_filename = f'map_{level}_{country}.html'
    else:
        # Standard map
        map_filename = f'map_{level}.html'

    map_path = os.path.join(os.path.dirname(__file__), 'static', map_filename)

    # For country-filtered maps, always regenerate to ensure fresh data
    # For standard maps, check if exists first
    if not country and os.path.exists(map_path):
        from flask import send_file
        return send_file(map_path)

    # Map doesn't exist or is country-filtered - generate it
    filter_msg = f" (country: {country})" if country else ""
    print(f"[MAP] Map for level {level}{filter_msg} generating on-demand...")

    # Check if we have any activities with GPS data
    activities_with_streams = get_activities_with_streams_count()
    if activities_with_streams == 0:
        return """
        <!DOCTYPE html>
        <html>
        <head><title>No Data</title></head>
        <body style="display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; font-family: Arial, sans-serif; background: #f5f5f5;">
            <div style="text-align: center; color: #666;">
                <h2>No GPS Data Available</h2>
                <p>Upload activities with GPS data to generate maps.</p>
            </div>
        </body>
        </html>
        """, 200

    # Generate ONLY the requested map (not all maps)
    try:
        from .map_generator import generate_single_level_map
        generate_single_level_map(level, country_code=country if country else None)

        # Check if map was generated
        if os.path.exists(map_path):
            from flask import send_file

            # Only kick off background generation for non-filtered maps
            if not country:
                import threading
                def generate_other_maps():
                    try:
                        print("[MAP] Background generation of other map levels starting...")
                        all_levels = ['lau', 0, 1, 2, 3]
                        for other_level in all_levels:
                            # Convert level to string for comparison
                            level_str = str(level)
                            other_level_str = str(other_level)

                            if level_str != other_level_str:
                                other_map_path = os.path.join(os.path.dirname(__file__), 'static', f'map_{other_level}.html')
                                if not os.path.exists(other_map_path):
                                    print(f"[MAP] Generating map for level {other_level} in background...")
                                    generate_single_level_map(other_level)
                        print("[MAP] Background map generation complete")
                    except Exception as e:
                        print(f"[MAP] Background generation error: {e}")

                thread = threading.Thread(target=generate_other_maps, daemon=True)
                thread.start()

            return send_file(map_path)
        else:
            return """
            <!DOCTYPE html>
            <html>
            <head><title>Map Generation Failed</title></head>
            <body style="display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; font-family: Arial, sans-serif; background: #f5f5f5;">
                <div style="text-align: center; color: #666;">
                    <h2>Map Generation Failed</h2>
                    <p>Please try refreshing the page or click "Update Activities".</p>
                </div>
            </body>
            </html>
            """, 500
    except Exception as e:
        print(f"[MAP] Error generating map: {e}")
        import traceback
        traceback.print_exc()
        return f"""
        <!DOCTYPE html>
        <html>
        <head><title>Error</title></head>
        <body style="display: flex; align-items: center; justify-content: center; height: 100vh; margin: 0; font-family: Arial, sans-serif; background: #f5f5f5;">
            <div style="text-align: center; color: #666;">
                <h2>Error Generating Map</h2>
                <p>{str(e)}</p>
                <p>Please click "Update Activities" to regenerate maps.</p>
            </div>
        </body>
        </html>
        """, 500


@app.route("/map")
def map_view():
    """Serve the generated map image."""
    from flask import send_file
    map_path = "static/map.png"
    if os.path.exists(map_path):
        return send_file(map_path, mimetype="image/png")
    else:
        return "Map not generated yet. Please run Update Activities.", 404
