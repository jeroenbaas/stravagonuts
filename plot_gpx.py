import os
import sys
import requests
import zipfile
import geopandas as gpd
from shapely.geometry import LineString, Point
import xml.etree.ElementTree as ET
import contextily as ctx
import matplotlib.pyplot as plt
from matplotlib.patches import Circle, Rectangle
import numpy as np


def draw_strava_finish_marker(ax, center, radius, zorder=7):
    """
    Draw a Strava-style checkered finish flag marker.
    White circle with black and white checkered pattern inside.
    """
    x0, y0 = center
    
    # Background white circle (solid fill)
    bg_circle = Circle(
        (x0, y0),
        radius=radius,
        facecolor='white',
        edgecolor='none',
        zorder=zorder
    )
    ax.add_patch(bg_circle)
    
    # Checkered pattern (6 rows x 6 columns for finer detail)
    checker_size = 6
    inner_radius = radius * 0.7  # Checkered area is smaller than outer circle
    square_size = (3 * inner_radius) / checker_size
    
    # Clip circle for checkered pattern
    clip_circle = Circle((x0, y0), radius=inner_radius, transform=ax.transData)
    
    for row in range(checker_size):
        for col in range(checker_size):
            # Only draw black squares (white is the background)
            if (row + col) % 2 == 0:
                x = x0 - inner_radius + col * square_size
                y = y0 - inner_radius + row * square_size
                
                rect = Rectangle(
                    (x, y),
                    square_size,
                    square_size,
                    facecolor='black',
                    edgecolor='none',
                    zorder=zorder + 1
                )
                ax.add_patch(rect)
                rect.set_clip_path(clip_circle)
    
    # Outer border (white ring with black outline)
    outer_ring = Circle(
        (x0, y0),
        radius=radius,
        facecolor='none',
        edgecolor='white',
        linewidth=4,
        zorder=zorder + 2
    )
    ax.add_patch(outer_ring)
    
    # Black outline
    black_outline = Circle(
        (x0, y0),
        radius=radius,
        facecolor='none',
        edgecolor='black',
        linewidth=1.5,
        zorder=zorder + 3
    )
    ax.add_patch(black_outline)


# --------------------------------------------------------
# Download and extract LAU shapefile (cached locally)
# --------------------------------------------------------

LAU_URL = (
    "https://gisco-services.ec.europa.eu/distribution/v2/lau/shp/LAU_RG_01M_2024_3035.shp.zip"
)


def ensure_lau_local(dir_path="./lau_data"):
    os.makedirs(dir_path, exist_ok=True)
    zip_path = os.path.join(dir_path, "LAU_2024.zip")

    # Download if missing
    if not os.path.exists(zip_path):
        print("Downloading LAU shapefile...")
        r = requests.get(LAU_URL)
        r.raise_for_status()
        with open(zip_path, "wb") as f:
            f.write(r.content)
        print("Saved:", zip_path)

    # Extract if not already
    shp_dir = os.path.join(dir_path, "shp")
    if not os.path.exists(shp_dir):
        print("Extracting LAU files...")
        os.makedirs(shp_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(shp_dir)
        print("Extracted to:", shp_dir)

    # Find .shp file
    for root, _, files in os.walk(shp_dir):
        for f in files:
            if f.endswith(".shp"):
                return os.path.join(root, f)

    raise FileNotFoundError("Could not locate LAU .shp file after extracting.")


# --------------------------------------------------------
# Load GPX from local file
# --------------------------------------------------------

def load_gpx_from_file(gpx_path: str) -> LineString:
    print("Loading GPX from file:", gpx_path)
    with open(gpx_path, "r", encoding="utf-8") as f:
        content = f.read()

    root = ET.fromstring(content)
    coords = []
    for trk in root.findall(".//{http://www.topografix.com/GPX/1/1}trk"):
        for seg in trk.findall(".//{http://www.topografix.com/GPX/1/1}trkseg"):
            for pt in seg.findall(".//{http://www.topografix.com/GPX/1/1}trkpt"):
                lat = float(pt.attrib["lat"])
                lon = float(pt.attrib["lon"])
                coords.append((lon, lat))
    
    # Fallback for GPX without namespace
    if not coords:
        for trk in root.findall("trk"):
            for seg in trk.findall("trkseg"):
                for pt in seg.findall("trkpt"):
                    lat = float(pt.attrib["lat"])
                    lon = float(pt.attrib["lon"])
                    coords.append((lon, lat))

    if not coords:
        raise ValueError("No trackpoints found in GPX file")

    return LineString(coords)


# --------------------------------------------------------
# Find overlapping LAU regions
# --------------------------------------------------------

def find_overlapping_lau(lau: gpd.GeoDataFrame, activity: LineString):
    # Ensure CRS is WGS84
    if lau.crs != "EPSG:4326":
        lau = lau.to_crs("EPSG:4326")

    # Fast bbox prefilter
    idx = list(lau.sindex.intersection(activity.bounds))
    candidates = lau.iloc[idx]

    # Exact intersection
    overlaps = candidates[candidates.intersects(activity)]
    return overlaps


# --------------------------------------------------------
# Strava-style map plot
# --------------------------------------------------------

def plot_strava_style(lau, overlapping, activity, save_path=None):
    """
    Plot in Strava style with muted background and highlighted route.
    """
    # Reproject to Web Mercator for basemap
    lau = lau.to_crs(epsg=3857)
    overlapping = overlapping.to_crs(epsg=3857)
    activity_gs = gpd.GeoSeries([activity], crs="EPSG:4326").to_crs(epsg=3857)

    fig, ax = plt.subplots(figsize=(12, 12))
    
    # Set white background (like Strava)
    fig.patch.set_facecolor('white')
    ax.set_facecolor('white')

    # Don't plot all LAU polygons - let the basemap show through
    # Only plot overlapping LAUs with subtle highlight
    overlapping.plot(
        ax=ax, 
        color="#B8D4E8",  # Light blue fill (matching Strava)
        alpha=0.5,  # More prominent fill
        edgecolor="#5A8FC4",  # Darker blue border
        linewidth=2.0  # Thicker border
    )

    # Draw activity line - Strava orange with white outline for pop
    line_geom = activity_gs.iloc[0]
    xs, ys = line_geom.xy
    
    # White outline (thicker)
    ax.plot(xs, ys, color='white', linewidth=5, solid_capstyle='round', zorder=4)
    # Orange line on top
    ax.plot(xs, ys, color='#FC4C02', linewidth=3, solid_capstyle='round', zorder=5)

    # Start and finish points
    start_pt = Point(activity.coords[0])
    finish_pt = Point(activity.coords[-1])
    start_pt_proj = gpd.GeoSeries([start_pt], crs="EPSG:4326").to_crs(epsg=3857).iloc[0]
    finish_pt_proj = gpd.GeoSeries([finish_pt], crs="EPSG:4326").to_crs(epsg=3857).iloc[0]

    # Start marker - solid green circle with white border
    start_circle_bg = Circle(
        (start_pt_proj.x, start_pt_proj.y),
        radius=1000,
        facecolor='#4CAF50',
        edgecolor='white',
        linewidth=4,
        zorder=6
    )
    ax.add_patch(start_circle_bg)
    
    start_circle_outline = Circle(
        (start_pt_proj.x, start_pt_proj.y),
        radius=1000,
        facecolor='none',
        edgecolor='black',
        linewidth=1.5,
        zorder=7
    )
    ax.add_patch(start_circle_outline)

    # Finish marker - checkered flag
    draw_strava_finish_marker(ax, (finish_pt_proj.x, finish_pt_proj.y), radius=1000, zorder=6)

    # Zoom to activity with margin
    if not overlapping.empty:
        minx, miny, maxx, maxy = overlapping.total_bounds
    else:
        minx, miny, maxx, maxy = activity_gs.total_bounds

    margin_x = (maxx - minx) * 0.12
    margin_y = (maxy - miny) * 0.12
    ax.set_xlim(minx - margin_x, maxx + margin_x)
    ax.set_ylim(miny - margin_y, maxy + margin_y)

    # Add basemap - use OpenStreetMap (clearer than Positron)
    ctx.add_basemap(
        ax,
        source=ctx.providers.OpenStreetMap.Mapnik,
        zoom='auto',
        attribution=False
    )

    ax.set_axis_off()
    plt.tight_layout(pad=0)

    if save_path:
        plt.savefig(save_path, dpi=300, bbox_inches="tight", facecolor='white')
        print(f"Map saved to {save_path}")
    else:
        plt.show()

    plt.close(fig)


# --------------------------------------------------------
# MAIN EXECUTION
# --------------------------------------------------------

if __name__ == "__main__":
    # Check command-line argument for GPX file
    if len(sys.argv) < 2:
        print("Usage: python lau_gpx_checker.py <gpx_file_path>")
        sys.exit(1)

    gpx_file_path = sys.argv[1]

    # Step 1 — Download LAU shapefile if missing
    shp_path = ensure_lau_local()

    # Step 2 — Load LAU polygons
    print("Loading LAU GeoDataFrame...")
    lau = gpd.read_file(shp_path)

    # Standardize column names
    lau = lau.rename(columns={
        "GISCO_ID": "LAU_ID",
        "LAU_NAME": "NAME_LATN"
    })

    print(f"LAU polygons loaded: {len(lau)}")

    # Step 3 — Load GPX file
    activity_line = load_gpx_from_file(gpx_file_path)

    # Step 4 — Find overlapping LAU regions
    overlapping = find_overlapping_lau(lau, activity_line)

    print("Matched LAU regions:")
    if len(overlapping) == 0:
        print("No overlapping LAU regions found.")
    else:
        print(overlapping[["LAU_ID", "NAME_LATN", "CNTR_CODE"]])

    # Step 5 — Generate map
    output_image = f"gpx_cache/{os.path.basename(gpx_file_path).replace('.gpx','.png')}"
    os.makedirs("gpx_cache", exist_ok=True)
    plot_strava_style(lau, overlapping, activity_line, save_path=output_image)