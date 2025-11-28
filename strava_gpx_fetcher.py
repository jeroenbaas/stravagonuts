import json
import os
import re
import requests
from xml.dom.minidom import Document

SECRETS_FILE = "secrets.json"
GPX_CACHE_DIR = "gpx_cache"

STREAMS_URL = "https://www.strava.com/api/v3/activities/{id}/streams?keys=latlng,time&key_by_type=true"
TOKEN_URL   = "https://www.strava.com/api/v3/oauth/token"


# -------------------------
# Secrets management
# -------------------------
def load_secrets():
    with open(SECRETS_FILE, "r") as f:
        return json.load(f)


def save_secrets(secrets):
    with open(SECRETS_FILE, "w") as f:
        json.dump(secrets, f, indent=4)


# -------------------------
# Refresh if expired
# -------------------------
def refresh_token(secrets):
    print("Refreshing Strava token...")
    r = requests.post(TOKEN_URL, data={
        "client_id": secrets["client_id"],
        "client_secret": secrets["client_secret"],
        "grant_type": "refresh_token",
        "refresh_token": secrets["refresh_token"]
    })
    r.raise_for_status()
    data = r.json()

    secrets["access_token"] = data["access_token"]
    secrets["refresh_token"] = data["refresh_token"]
    save_secrets(secrets)

    print("✓ Token refreshed")
    return secrets


# -------------------------
# Extract activity ID
# -------------------------
def extract_activity_id(url):
    m = re.search(r"/activities/(\d+)", url)
    if not m:
        raise ValueError("Could not extract activity ID from URL")
    return int(m.group(1))


# -------------------------
# Download streams
# -------------------------
def get_streams(activity_id, secrets):
    url = STREAMS_URL.format(id=activity_id)
    headers = {"Authorization": f"Bearer {secrets['access_token']}"}

    r = requests.get(url, headers=headers)
    if r.status_code == 401:
        # token expired
        secrets = refresh_token(secrets)
        headers = {"Authorization": f"Bearer {secrets['access_token']}"}
        r = requests.get(url, headers=headers)

    r.raise_for_status()
    return r.json()


# -------------------------
# Convert streams → GPX
# -------------------------
def streams_to_gpx(latlng, time):
    doc = Document()
    gpx = doc.createElement("gpx")
    gpx.setAttribute("creator", "strava-api")
    gpx.setAttribute("version", "1.1")
    doc.appendChild(gpx)

    trk = doc.createElement("trk")
    gpx.appendChild(trk)

    trkseg = doc.createElement("trkseg")
    trk.appendChild(trkseg)

    for i, (lat, lon) in enumerate(latlng):
        trkpt = doc.createElement("trkpt")
        trkpt.setAttribute("lat", str(lat))
        trkpt.setAttribute("lon", str(lon))

        if time:
            t = doc.createElement("time")
            t.appendChild(doc.createTextNode(str(time[i])))
            trkpt.appendChild(t)

        trkseg.appendChild(trkpt)

    return doc.toprettyxml(indent="  ")


# -------------------------
# Main GPX fetcher
# -------------------------
def fetch_gpx(url):
    secrets = load_secrets()
    os.makedirs(GPX_CACHE_DIR, exist_ok=True)

    activity_id = extract_activity_id(url)
    out_path = f"{GPX_CACHE_DIR}/{activity_id}.gpx"

    if os.path.exists(out_path):
        print("Already cached:", out_path)
        return out_path

    print("Fetching streams for activity", activity_id)
    streams = get_streams(activity_id, secrets)

    if "latlng" not in streams:
        raise RuntimeError("This activity has no lat/lng stream (maybe private?)")

    latlng = streams["latlng"]["data"]
    time = streams.get("time", {}).get("data", None)

    gpx_text = streams_to_gpx(latlng, time)

    with open(out_path, "w") as f:
        f.write(gpx_text)

    print("✓ Saved GPX:", out_path)
    return out_path


# -------------------------
# CLI entry point
# -------------------------
if __name__ == "__main__":
    import sys
    if len(sys.argv) < 2:
        print("Usage: python fetch_strava_gpx.py <strava_activity_url>")
        exit(1)

    url = sys.argv[1]
    fetch_gpx(url)
