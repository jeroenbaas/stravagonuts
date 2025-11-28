import json
import os
import sys
import requests
import time
from pathlib import Path
import geopandas as gpd
from shapely.geometry import LineString, Point, MultiLineString
import xml.etree.ElementTree as ET
import contextily as ctx
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
import numpy as np
from tqdm import tqdm

SECRETS_FILE = "secrets.json"
TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"
ACTIVITIES_URL = "https://www.strava.com/api/v3/athlete/activities"
STREAMS_URL = "https://www.strava.com/api/v3/activities/{id}/streams?keys=latlng,time&key_by_type=true"

LAU_URL = "https://gisco-services.ec.europa.eu/distribution/v2/lau/shp/LAU_RG_01M_2024_3035.shp.zip"


def draw_strava_finish_marker(ax, center, radius, zorder=7):
    """Draw a Strava-style checkered finish flag marker."""
    x0, y0 = center
    
    bg_circle = Circle((x0, y0), radius=radius, facecolor='white', 
                       edgecolor='none', zorder=zorder)
    ax.add_patch(bg_circle)
    
    checker_size = 6
    inner_radius = radius * 0.7
    square_size = (2 * inner_radius) / checker_size
    
    clip_circle = Circle((x0, y0), radius=inner_radius, transform=ax.transData)
    
    for row in range(checker_size):
        for col in range(checker_size):
            if (row + col) % 2 == 0:
                x = x0 - inner_radius + col * square_size
                y = y0 - inner_radius + row * square_size
                
                rect = Rectangle((x, y), square_size, square_size,
                               facecolor='black', edgecolor='none', zorder=zorder + 1)
                ax.add_patch(rect)
                rect.set_clip_path(clip_circle)
    
    outer_ring = Circle((x0, y0), radius=radius, facecolor='none',
                        edgecolor='white', linewidth=4, zorder=zorder + 2)
    ax.add_patch(outer_ring)
    
    black_outline = Circle((x0, y0), radius=radius, facecolor='none',
                           edgecolor='black', linewidth=1.5, zorder=zorder + 3)
    ax.add_patch(black_outline)


# --------------------------------------------------------
# Secrets and token management
# --------------------------------------------------------

def load_secrets():
    with open(SECRETS_FILE, "r") as f:
        return json.load(f)


def save_secrets(secrets):
    with open(SECRETS_FILE, "w") as f:
        json.dump(secrets, f, indent=4)


def refresh_token(secrets):
    print("🔄 Refreshing Strava token...")
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


# --------------------------------------------------------
# Fetch all activities for athlete
# --------------------------------------------------------

def get_all_activities(secrets):
    """Fetch all activities from Strava API with pagination."""
    headers = {"Authorization": f"Bearer {secrets['access_token']}"}
    
    all_activities = []
    page = 1
    per_page = 200  # Max allowed by Strava
    
    print("📥 Fetching activities list...")
    
    while True:
        params = {"page": page, "per_page": per_page}
        r = requests.get(ACTIVITIES_URL, headers=headers, params=params)
        
        if r.status_code == 401:
            secrets = refresh_token(secrets)
            headers = {"Authorization": f"Bearer {secrets['access_token']}"}
            r = requests.get(ACTIVITIES_URL, headers=headers, params=params)
        
        r.raise_for_status()
        activities = r.json()
        
        if not activities:
            break
        
        all_activities.extend(activities)
        print(f"  Page {page}: {len(activities)} activities")
        
        if len(activities) < per_page:
            break
        
        page += 1
        time.sleep(0.1)  # Rate limiting
    
    print(f"✓ Found {len(all_activities)} total activities")
    return all_activities


# --------------------------------------------------------
# Download activity streams
# --------------------------------------------------------

def get_activity_streams(activity_id, secrets):
    """Download latlng streams for a single activity."""
    url = STREAMS_URL.format(id=activity_id)
    headers = {"Authorization": f"Bearer {secrets['access_token']}"}
    
    r = requests.get(url, headers=headers)
    
    if r.status_code == 401:
        secrets = refresh_token(secrets)
        headers = {"Authorization": f"Bearer {secrets['access_token']}"}
        r = requests.get(url, headers=headers)
    
    if r.status_code == 404:
        return None  # Activity has no GPS data
    
    r.raise_for_status()
    return r.json()


def streams_to_linestring(streams):
    """Convert Strava streams to Shapely LineString."""
    if "latlng" not in streams or not streams["latlng"]["data"]:
        return None
    
    latlng = streams["latlng"]["data"]
    # Convert from [lat, lon] to [lon, lat] for Shapely
    coords = [(lon, lat) for lat, lon in latlng]
    
    if len(coords) < 2:
        return None
    
    return LineString(coords)


# --------------------------------------------------------
# Download and cache GPX files
# --------------------------------------------------------

def download_all_gpx(activities, user_dir, secrets):
    """Download GPX data for all activities."""
    gpx_dir = user_dir / "gpx"
    gpx_dir.mkdir(exist_ok=True)
    
    linestrings = []
    
    print(f"\n📍 Downloading GPS data for {len(activities)} activities...")
    
    for activity in tqdm(activities, desc="Downloading activities"):
        activity_id = activity["id"]
        gpx_path = gpx_dir / f"{activity_id}.json"
        
        # Check cache
        if gpx_path.exists():
            try:
                with open(gpx_path, "r") as f:
                    streams = json.load(f)
                linestring = streams_to_linestring(streams)
                if linestring:
                    linestrings.append(linestring)
                continue
            except:
                pass
        
        # Download streams
        try:
            streams = get_activity_streams(activity_id, secrets)
            
            if streams and "latlng" in streams:
                # Cache to disk
                with open(gpx_path, "w") as f:
                    json.dump(streams, f)
                
                linestring = streams_to_linestring(streams)
                if linestring:
                    linestrings.append(linestring)
            
            time.sleep(0.05)  # Rate limiting
            
        except Exception as e:
            tqdm.write(f"  ⚠️  Failed to download activity {activity_id}: {e}")
            continue
    
    print(f"✓ Successfully loaded {len(linestrings)} activities with GPS data")
    return linestrings


# --------------------------------------------------------
# LAU shapefile management
# --------------------------------------------------------

def ensure_lau_local(dir_path="./lau_data"):
    import zipfile
    
    os.makedirs(dir_path, exist_ok=True)
    zip_path = os.path.join(dir_path, "LAU_2024.zip")

    if not os.path.exists(zip_path):
        print("📥 Downloading LAU shapefile...")
        r = requests.get(LAU_URL)
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            f.write(r.content)
        print("✓ Downloaded LAU shapefile")

    shp_dir = os.path.join(dir_path, "shp")
    if not os.path.exists(shp_dir):
        print("📦 Extracting LAU files...")
        os.makedirs(shp_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(shp_dir)
        print("✓ Extracted LAU files")

    for root, _, files in os.walk(shp_dir):
        for f in files:
            if f.endswith(".shp"):
                return os.path.join(root, f)

    raise FileNotFoundError("Could not locate LAU .shp file after extracting.")


# --------------------------------------------------------
# Find overlapping LAU regions for all activities
# --------------------------------------------------------

def find_all_overlapping_lau(lau, linestrings):
    """Find all LAU regions that overlap with any activity."""
    print("\n🗺️  Finding overlapping municipalities...")
    
    if lau.crs != "EPSG:4326":
        lau = lau.to_crs("EPSG:4326")
    
    # Combine all linestrings into one geometry for efficient processing
    multi_line = MultiLineString(linestrings)
    
    # Fast bbox prefilter
    idx = list(lau.sindex.intersection(multi_line.bounds))
    candidates = lau.iloc[idx]
    
    # Exact intersection
    overlapping_set = set()
    
    for linestring in tqdm(linestrings, desc="Checking municipalities"):
        idx = list(candidates.sindex.intersection(linestring.bounds))
        local_candidates = candidates.iloc[idx]
        overlaps = local_candidates[local_candidates.intersects(linestring)]
        overlapping_set.update(overlaps.index)
    
    overlapping = lau.loc[list(overlapping_set)]
    
    print(f"✓ Found {len(overlapping)} unique municipalities crossed")
    return overlapping


# --------------------------------------------------------
# Plot combined map
# --------------------------------------------------------

def plot_all_activities_map(lau, overlapping, linestrings, save_path):
    """Plot all activities on a single map."""
    print("\n🎨 Generating combined map...")
    
    # Reproject to Web Mercator
    lau = lau.to_crs(epsg=3857)
    overlapping = overlapping.to_crs(epsg=3857)
    
    all_lines_gs = gpd.GeoSeries(linestrings, crs="EPSG:4326").to_crs(epsg=3857)
    
    fig, ax = plt.subplots(figsize=(14, 14))
    
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')
    
    # Plot overlapping LAUs
    overlapping.plot(
        ax=ax,
        color="#B8D4E8",
        alpha=0.5,
        edgecolor="#5A8FC4",
        linewidth=2.0
    )
    
    # Plot all activity lines
    for line_geom in tqdm(all_lines_gs, desc="Drawing routes"):
        xs, ys = line_geom.xy
        ax.plot(xs, ys, color='white', linewidth=2, solid_capstyle='round', zorder=4, alpha=0.8)
        ax.plot(xs, ys, color='#FC4C02', linewidth=1, solid_capstyle='round', zorder=5, alpha=0.6)
    
    # Zoom to overlapping regions
    if not overlapping.empty:
        minx, miny, maxx, maxy = overlapping.total_bounds
    else:
        minx, miny, maxx, maxy = all_lines_gs.total_bounds
    
    margin_x = (maxx - minx) * 0.08
    margin_y = (maxy - miny) * 0.08
    ax.set_xlim(minx - margin_x, maxx + margin_x)
    ax.set_ylim(miny - margin_y, maxy + margin_y)
    
    # Add basemap
    try:
        ctx.add_basemap(
            ax,
            source=ctx.providers.Stamen.Terrain,
            zoom='auto',
            attribution=False
        )
    except:
        ctx.add_basemap(
            ax,
            source=ctx.providers.OpenStreetMap.Mapnik,
            zoom='auto',
            attribution=False
        )
    
    ax.set_axis_off()
    plt.tight_layout(pad=0)
    
    plt.savefig(save_path, dpi=300, bbox_inches="tight", facecolor='white')
    print(f"✓ Map saved to {save_path}")
    plt.close(fig)


# --------------------------------------------------------
# Main execution
# --------------------------------------------------------

def main(user_id=None):
    secrets = load_secrets()
    
    # Create user directory
    if user_id:
        user_dir = Path("users") / str(user_id)
    else:
        user_dir = Path("users") / "default"
    
    user_dir.mkdir(parents=True, exist_ok=True)
    
    print(f"🏃 Processing activities for user directory: {user_dir}")
    
    # Step 1: Get all activities
    activities = get_all_activities(secrets)
    
    if not activities:
        print("❌ No activities found")
        return
    
    # Step 2: Download GPS data for all activities
    linestrings = download_all_gpx(activities, user_dir, secrets)
    
    if not linestrings:
        print("❌ No activities with GPS data found")
        return
    
    # Step 3: Load LAU shapefile
    shp_path = ensure_lau_local()
    print("\n📂 Loading LAU municipalities database...")
    lau = gpd.read_file(shp_path)
    lau = lau.rename(columns={
        "GISCO_ID": "LAU_ID",
        "LAU_NAME": "NAME_LATN"
    })
    print(f"✓ Loaded {len(lau)} municipalities")
    
    # Step 4: Find overlapping LAU regions
    overlapping = find_all_overlapping_lau(lau, linestrings)
    
    # Save municipality list
    csv_path = user_dir / "municipalities.csv"
    overlapping[["LAU_ID", "NAME_LATN", "CNTR_CODE"]].to_csv(csv_path, index=False)
    print(f"✓ Municipality list saved to {csv_path}")
    
    # Step 5: Generate combined map
    map_path = user_dir / "all_activities_map.png"
    plot_all_activities_map(lau, overlapping, linestrings, map_path)
    
    print(f"\n🎉 Complete! Visited {len(overlapping)} municipalities across {len(linestrings)} activities")
    print(f"📁 All files saved to: {user_dir}")


if __name__ == "__main__":
    user_id = sys.argv[1] if len(sys.argv) > 1 else None
    main(user_id)