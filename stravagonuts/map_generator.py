import os
import requests
import zipfile

from .database import (
    get_all_activities_with_streams, link_activity_lau,
    update_lau_first_visited_dates, link_activity_nuts,
    update_nuts_first_visited_dates, mark_activities_processed_for_regions
)


LAU_URL = "https://gisco-services.ec.europa.eu/distribution/v2/lau/shp/LAU_RG_01M_2024_3035.shp.zip"
LAU_DATA_DIR = "lau_data"
STATIC_DIR = os.path.join(os.path.dirname(__file__), 'static')


def ensure_lau_shapefile():
    """Download and extract LAU shapefile if not present."""
    os.makedirs(LAU_DATA_DIR, exist_ok=True)
    zip_path = os.path.join(LAU_DATA_DIR, "LAU_2024.zip")

    if not os.path.exists(zip_path):
        print("Downloading LAU shapefile...")
        response = requests.get(LAU_URL)
        response.raise_for_status()
        with open(zip_path, "wb") as f:
            f.write(response.content)

    shp_dir = os.path.join(LAU_DATA_DIR, "shp")
    if not os.path.exists(shp_dir):
        print("Extracting LAU shapefile...")
        os.makedirs(shp_dir, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(shp_dir)

    # Find the .shp file
    for root, _, files in os.walk(shp_dir):
        for file in files:
            if file.endswith(".shp"):
                return os.path.join(root, file)

    raise FileNotFoundError("Could not locate LAU .shp file after extracting")


def streams_to_linestring(streams):
    """Convert Strava streams to Shapely LineString."""
    if "latlng" not in streams or not streams["latlng"]["data"]:
        return None

    latlng = streams["latlng"]["data"]
    coords = [(lon, lat) for lat, lon in latlng]

    if len(coords) < 2:
        return None

    from shapely.geometry import LineString
    return LineString(coords)


def find_overlapping_lau(lau, linestrings):
    """Find all LAU regions that overlap with any activity."""
    if lau.crs != "EPSG:4326":
        lau = lau.to_crs("EPSG:4326")

    from shapely.geometry import MultiLineString
    multi_line = MultiLineString(linestrings)

    # Fast bbox prefilter
    idx = list(lau.sindex.intersection(multi_line.bounds))
    candidates = lau.iloc[idx]

    # Exact intersection
    overlapping_set = set()
    activity_lau_map = {}

    for line_idx, linestring in enumerate(linestrings):
        activity_lau_map[line_idx] = []
        idx = list(candidates.sindex.intersection(linestring.bounds))
        local_candidates = candidates.iloc[idx]
        overlaps = local_candidates[local_candidates.intersects(linestring)]

        for overlap_idx in overlaps.index:
            overlapping_set.add(overlap_idx)
            activity_lau_map[line_idx].append(overlap_idx)

    overlapping = lau.loc[list(overlapping_set)]

    return overlapping, activity_lau_map


def plot_activities_map(lau, overlapping, linestrings, save_path):
    """Generate map with all activities and overlapping LAU regions."""
    # Reproject to Web Mercator
    lau = lau.to_crs(epsg=3857)
    overlapping = overlapping.to_crs(epsg=3857)

    import geopandas as gpd
    import contextily as ctx
    import matplotlib
    matplotlib.use('Agg')
    import matplotlib.pyplot as plt

    all_lines_gs = gpd.GeoSeries(linestrings, crs="EPSG:4326").to_crs(epsg=3857)

    fig, ax = plt.subplots(figsize=(14, 14))

    fig.patch.set_facecolor("white")
    ax.set_facecolor("white")

    # Plot overlapping LAUs
    overlapping.plot(
        ax=ax,
        color="#B8D4E8",
        alpha=0.5,
        edgecolor="#5A8FC4",
        linewidth=2.0,
    )

    # Plot all activity lines
    for line_geom in all_lines_gs:
        xs, ys = line_geom.xy
        ax.plot(
            xs, ys, color="white", linewidth=2, solid_capstyle="round", zorder=4, alpha=0.8
        )
        ax.plot(
            xs, ys, color="#FC4C02", linewidth=1, solid_capstyle="round", zorder=5, alpha=0.6
        )

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
            ax, source=ctx.providers.Stamen.Terrain, zoom="auto", attribution=False
        )
    except:
        ctx.add_basemap(
            ax, source=ctx.providers.OpenStreetMap.Mapnik, zoom="auto", attribution=False
        )

    ax.set_axis_off()
    plt.tight_layout(pad=0)

    plt.savefig(save_path, dpi=300, bbox_inches="tight", facecolor="white")
    plt.close(fig)


def generate_map(status_dict=None):
    """Generate map from activities in database."""
    print("[MAP] Generating map...")

    # Clean up existing map files to ensure freshness
    try:
        if os.path.exists(STATIC_DIR):
            for f in os.listdir(STATIC_DIR):
                if f.startswith("map_") and f.endswith(".html"):
                    try:
                        os.remove(os.path.join(STATIC_DIR, f))
                    except Exception as e:
                        print(f"[MAP] Error deleting {f}: {e}")
    except Exception as e:
        print(f"[MAP] Error cleaning up static directory: {e}")

    # Load LAU shapefile
    print("[MAP] Loading LAU shapefile...")
    import geopandas as gpd
    shp_path = ensure_lau_shapefile()
    lau = gpd.read_file(shp_path)
    lau = lau.rename(columns={"GISCO_ID": "LAU_ID", "LAU_NAME": "NAME_LATN"})
    print(f"[MAP] Loaded {len(lau)} LAU regions")

    # Get all activities with streams
    print("[MAP] Loading activities from database...")
    activities = get_all_activities_with_streams()

    if not activities:
        print("[MAP] No activities with GPS data found")
        return

    print(f"[MAP] Found {len(activities)} activities with streams")

    # Convert streams to linestrings
    linestrings = []
    activity_ids = []

    for activity in activities:
        streams = activity.get("streams_data")
        if streams:
            linestring = streams_to_linestring(streams)
            if linestring:
                linestrings.append(linestring)
                activity_ids.append(activity["id"])

    if not linestrings:
        print("[MAP] No valid GPS tracks found")
        return

    print(f"[MAP] Processing {len(linestrings)} activities with GPS data")

    # Find overlapping LAU regions
    print("[MAP] Finding overlapping LAU regions...")
    overlapping, activity_lau_map = find_overlapping_lau(lau, linestrings)

    print(f"[MAP] Found {len(overlapping)} unique LAU regions")

    # Link activities to LAU regions (regions already exist from startup)
    print("[MAP] Linking activities to LAU regions...")
    total_links = 0
    for line_idx, lau_indices in activity_lau_map.items():
        activity_id = activity_ids[line_idx]
        for lau_idx in lau_indices:
            lau_row = lau.loc[lau_idx]
            try:
                link_activity_lau(activity_id, lau_row["LAU_ID"])
                total_links += 1
            except Exception as e:
                print(f"[MAP] ERROR linking activity {activity_id} to LAU {lau_row['LAU_ID']}: {e}")

    print(f"[MAP] Successfully created {total_links} activity-LAU links")

    # Update first_visited dates based on earliest activity
    print("[MAP] Updating first visited dates...")
    update_lau_first_visited_dates()

    # Process NUTS regions at all levels
    print("[MAP] Processing NUTS regions...")
    try:
        process_nuts_regions(activity_ids, activity_lau_map, lau)
    except Exception as e:
        print(f"[MAP] ERROR processing NUTS regions: {e}")
        import traceback
        traceback.print_exc()

    # Mark all processed activities as complete
    print("[MAP] Marking activities as processed...")
    mark_activities_processed_for_regions(activity_ids)

    # Generate static map (LAU only for backward compatibility)
    print("[MAP] Plotting static map image...")
    os.makedirs(STATIC_DIR, exist_ok=True)
    map_path = os.path.join(STATIC_DIR, "map.png")
    plot_activities_map(lau, overlapping, linestrings, map_path)
    print(f"[MAP] Static map saved to {map_path}")

    # Generate interactive maps for all levels
    print("[MAP] Generating interactive maps for all levels...")
    levels = ['lau', 0, 1, 2, 3]
    for idx, level in enumerate(levels):
        level_name = f"NUTS{level}" if isinstance(level, int) else "LAU"
        interactive_map_path = os.path.join(STATIC_DIR, f"map_{level}.html")
        print(f"[MAP] Generating {level_name} map...")

        # Update status for UI
        if status_dict:
            status_dict["stage"] = "Generating maps"
            status_dict["progress"] = idx
            status_dict["total"] = len(levels)
            status_dict["message"] = f"Creating {level_name} interactive map..."

        generate_level_map(level, linestrings, interactive_map_path)

    # Final status update
    if status_dict:
        status_dict["progress"] = len(levels)
        status_dict["total"] = len(levels)
        status_dict["message"] = "All maps generated successfully!"

    # Symlink default map to LAU (for backward compatibility)
    default_map = os.path.join(STATIC_DIR, "map.html")
    lau_map = os.path.join(STATIC_DIR, "map_lau.html")
    if os.path.exists(default_map):
        os.remove(default_map)
    if os.path.exists(lau_map):
        import shutil
        shutil.copy(lau_map, default_map)

    print(f"[MAP] All interactive maps generated")


def generate_interactive_map(lau, overlapping, linestrings, save_path):
    """Generate interactive Folium map with OpenStreetMap."""
    print("[MAP] Creating interactive Folium map...")

    # Convert to WGS84 for Folium (EPSG:4326)
    if lau.crs != "EPSG:4326":
        lau = lau.to_crs("EPSG:4326")
    if overlapping.crs != "EPSG:4326":
        overlapping = overlapping.to_crs("EPSG:4326")

    # Calculate center and bounds
    import geopandas as gpd
    import folium
    from folium import plugins
    all_lines_gs = gpd.GeoSeries(linestrings, crs="EPSG:4326")
    bounds = all_lines_gs.total_bounds  # minx, miny, maxx, maxy
    center_lat = (bounds[1] + bounds[3]) / 2
    center_lon = (bounds[0] + bounds[2]) / 2

    # Create map
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=10,
        tiles='OpenStreetMap',
        control_scale=True
    )

    # Add LAU regions as polygons
    print(f"[MAP] Adding {len(overlapping)} LAU regions to map...")
    for idx, row in overlapping.iterrows():
        folium.GeoJson(
            row['geometry'],
            style_function=lambda x: {
                'fillColor': '#B8D4E8',
                'color': '#5A8FC4',
                'weight': 2,
                'fillOpacity': 0.4
            },
            tooltip=f"{row['NAME_LATN']} ({row['CNTR_CODE']})"
        ).add_to(m)

    # Add activity routes
    print(f"[MAP] Adding {len(linestrings)} activity routes to map...")
    for linestring in linestrings:
        coords = [(lat, lon) for lon, lat in linestring.coords]  # Swap to lat, lon for Folium
        folium.PolyLine(
            coords,
            color='#FC4C02',
            weight=3,
            opacity=0.7,
            popup='Activity Route'
        ).add_to(m)

    # Fit bounds
    southwest = [bounds[1], bounds[0]]
    northeast = [bounds[3], bounds[2]]
    m.fit_bounds([southwest, northeast])

    # Add fullscreen button
    plugins.Fullscreen().add_to(m)

    # Save map
    m.save(save_path)
    print(f"[MAP] Interactive map saved successfully")


def process_nuts_regions(activity_ids, activity_lau_map, lau_gdf):
    """Link activities to existing NUTS regions (regions already loaded on startup)."""

    # Load LAU to NUTS mappings from database (already populated on startup)
    print("[MAP] Loading LAU to NUTS mappings from database...")
    from .database import get_db

    lau_to_nuts = {}
    with get_db() as conn:
        cursor = conn.cursor()
        cursor.execute("""
            SELECT lau_id, nuts0_code, nuts1_code, nuts2_code, nuts3_code
            FROM regions.lau_nuts_mapping
        """)
        for row in cursor.fetchall():
            lau_to_nuts[row['lau_id']] = {
                'NUTS0': row['nuts0_code'],
                'NUTS1': row['nuts1_code'],
                'NUTS2': row['nuts2_code'],
                'NUTS3': row['nuts3_code']
            }

    if len(lau_to_nuts) == 0:
        print("[MAP] WARNING: No LAU-NUTS mappings found in database. Run region initialization first.")
        return

    print(f"[MAP] Loaded {len(lau_to_nuts)} LAU-NUTS mappings from database")

    # For each activity, collect NUTS codes at all levels
    activity_nuts_links = {0: set(), 1: set(), 2: set(), 3: set()}  # level -> set of (activity_id, nuts_code)

    print("[MAP] Mapping activities to NUTS regions...")
    matched_count = 0
    unmatched_lau_codes = set()

    for line_idx, lau_indices in activity_lau_map.items():
        activity_id = activity_ids[line_idx]

        for lau_idx in lau_indices:
            lau_row = lau_gdf.loc[lau_idx]
            lau_code = lau_row["LAU_ID"]

            # Look up NUTS codes for this LAU from database
            if lau_code in lau_to_nuts:
                matched_count += 1
                nuts_mapping = lau_to_nuts[lau_code]

                # Link activity to each NUTS level
                for level in [0, 1, 2, 3]:
                    nuts_code = nuts_mapping[f'NUTS{level}']
                    activity_nuts_links[level].add((activity_id, nuts_code))
            else:
                unmatched_lau_codes.add(lau_code)

    print(f"[MAP] Matched {matched_count} LAU codes, {len(unmatched_lau_codes)} unmatched")
    if unmatched_lau_codes:
        print(f"[MAP] Sample unmatched LAU codes: {list(unmatched_lau_codes)[:10]}")

    # Link activities to existing NUTS regions (regions already exist in database)
    for level in [0, 1, 2, 3]:
        print(f"[MAP] Linking activities to NUTS level {level}...")

        # Get unique NUTS codes for this level
        nuts_codes_for_level = set(nuts_code for _, nuts_code in activity_nuts_links[level])

        print(f"[MAP] Found {len(nuts_codes_for_level)} unique NUTS{level} regions to link")

        # Link activities to NUTS regions (regions already exist from startup)
        for activity_id, nuts_code in activity_nuts_links[level]:
            link_activity_nuts(activity_id, nuts_code)

    # Update first visited dates for NUTS
    print("[MAP] Updating NUTS first visited dates...")
    update_nuts_first_visited_dates()

    print("[MAP] NUTS processing complete!")


def generate_single_level_map(level, country_code=None):
    """Generate a single map for the specified level only.

    Args:
        level: 'lau', 0, 1, 2, or 3
        country_code: Optional NUTS0 country code to filter by
    """
    filter_msg = f" (country: {country_code})" if country_code else ""
    print(f"[MAP] Generating single map for level: {level}{filter_msg}")

    # Get all activities with streams
    activities = get_all_activities_with_streams()

    if not activities:
        print("[MAP] No activities with GPS data found")
        return

    # Convert streams to linestrings
    linestrings = []
    for activity in activities:
        streams = activity.get("streams_data")
        if streams:
            linestring = streams_to_linestring(streams)
            if linestring:
                linestrings.append(linestring)

    if not linestrings:
        print("[MAP] No valid GPS tracks found")
        return

    # Generate map for this level only
    # Use absolute path relative to package
    import os
    static_dir = os.path.join(os.path.dirname(__file__), 'static')
    os.makedirs(static_dir, exist_ok=True)

    # Filename includes country code if filtered
    filename = f"map_{level}_{country_code}.html" if country_code else f"map_{level}.html"
    map_path = os.path.join(static_dir, filename)

    print(f"[MAP] Generating map for level {level}{filter_msg}...")
    generate_level_map(level, linestrings, map_path, country_code=country_code)
    print(f"[MAP] Map saved to {map_path}")


def generate_level_map(level, linestrings, save_path, country_code=None):
    """Generate interactive map for a specific administrative level.

    Args:
        level: 'lau', 0, 1, 2, or 3
        linestrings: List of activity linestrings
        save_path: Where to save the HTML map
        country_code: Optional NUTS0 country code to filter by
    """
    filter_msg = f" (country: {country_code})" if country_code else ""
    print(f"[MAP] Generating interactive map for level: {level}{filter_msg}")

    from .database import get_db
    from shapely import wkt

    if level == 'lau':
        # Get visited LAU regions from database WITH geometry
        # Build GeoDataFrame from database
        geometries = []
        names = []
        codes = []

        with get_db() as conn:
            cursor = conn.cursor()
            query = """
                SELECT lau_id, name, geometry
                FROM regions.lau_regions
                WHERE lau_id IN (SELECT DISTINCT lau_id FROM activity_lau)
            """
            params = ()

            if country_code:
                query += " AND country_code = ?"
                params = (country_code,)

            cursor.execute(query, params)
            for row in cursor.fetchall():
                if row['geometry']:
                    geometries.append(wkt.loads(row['geometry']))
                    names.append(row['name'])
                    codes.append(row['lau_id'])

        import geopandas as gpd
        overlapping = gpd.GeoDataFrame({
            'LAU_ID': codes,
            'NAME_LATN': names,
            'geometry': geometries
        }, crs="EPSG:3035")

        name_col = 'NAME_LATN'
        code_col = 'LAU_ID'
    else:
        # Get visited NUTS regions from database WITH geometry
        # Build GeoDataFrame from database
        geometries = []
        names = []
        codes = []

        with get_db() as conn:
            cursor = conn.cursor()
            query = """
                SELECT nuts_code, name, geometry
                FROM regions.nuts_regions
                WHERE level = ? AND nuts_code IN (SELECT DISTINCT nuts_code FROM activity_nuts)
            """
            params = [level]

            if country_code:
                query += " AND country_code = ?"
                params.append(country_code)

            cursor.execute(query, tuple(params))
            for row in cursor.fetchall():
                if row['geometry']:
                    geometries.append(wkt.loads(row['geometry']))
                    names.append(row['name'])
                    codes.append(row['nuts_code'])

        import geopandas as gpd
        overlapping = gpd.GeoDataFrame({
            'NUTS_CODE': codes,
            'NUTS_NAME': names,
            'geometry': geometries
        }, crs="EPSG:3035")

        name_col = 'NUTS_NAME'
        code_col = 'NUTS_CODE'

    # Generate interactive map
    generate_interactive_map_generic(overlapping, linestrings, save_path, name_col, code_col)


def generate_interactive_map_generic(overlapping, linestrings, save_path, name_col, code_col):
    """Generic interactive map generator for any administrative level."""

    # Convert to WGS84 for Folium
    if overlapping.crs != "EPSG:4326":
        overlapping = overlapping.to_crs("EPSG:4326")

    # Simplify geometries to reduce file size (tolerance in degrees, ~100m at equator)
    print(f"[MAP] Simplifying {len(overlapping)} region geometries...")
    overlapping['geometry'] = overlapping['geometry'].simplify(tolerance=0.001, preserve_topology=True)

    # Use region bounds for center and zoom if we have regions
    # Otherwise fall back to activity bounds
    if not overlapping.empty:
        bounds = overlapping.total_bounds  # Use region bounds for better zoom
    else:
        import geopandas as gpd
        all_lines_gs = gpd.GeoSeries(linestrings, crs="EPSG:4326")
        bounds = all_lines_gs.total_bounds

    center_lat = (bounds[1] + bounds[3]) / 2
    center_lon = (bounds[0] + bounds[2]) / 2

    # Create map
    import folium
    from folium import plugins
    m = folium.Map(
        location=[center_lat, center_lon],
        zoom_start=10,
        tiles='OpenStreetMap',
        control_scale=True
    )
    
    # Add regions
    for idx, row in overlapping.iterrows():
        region_name = row.get(name_col, row.get(code_col, 'Unknown'))
        region_code = row.get(code_col, '')
        
        folium.GeoJson(
            row['geometry'],
            style_function=lambda x: {
                'fillColor': '#B8D4E8',
                'color': '#5A8FC4',
                'weight': 2,
                'fillOpacity': 0.4
            },
            tooltip=f"{region_name} ({region_code})"
        ).add_to(m)
    
    # Add activity routes (simplified to reduce file size)
    print(f"[MAP] Adding {len(linestrings)} activity routes...")
    for idx, linestring in enumerate(linestrings):
        # Simplify activity linestrings (tolerance ~50m at equator)
        simplified_line = linestring.simplify(tolerance=0.0005, preserve_topology=False)
        coords = [(lat, lon) for lon, lat in simplified_line.coords]

        # Only add if we have at least 2 points after simplification
        if len(coords) >= 2:
            folium.PolyLine(
                coords,
                color='#FC4C02',
                weight=3,
                opacity=0.7,
                popup=f'Activity {idx + 1}'
            ).add_to(m)
    
    # Fit bounds
    southwest = [bounds[1], bounds[0]]
    northeast = [bounds[3], bounds[2]]
    m.fit_bounds([southwest, northeast])
    
    # Add fullscreen button
    plugins.Fullscreen().add_to(m)

    # Add data attribution
    attribution_html = '''
    <div style="position: fixed;
                bottom: 10px;
                left: 50%;
                transform: translateX(-50%);
                background: white;
                padding: 8px 15px;
                border: 2px solid rgba(0,0,0,0.2);
                border-radius: 4px;
                font-size: 11px;
                z-index: 9999;
                box-shadow: 0 1px 5px rgba(0,0,0,0.2);">
        <strong>Data:</strong> © European Commission – Eurostat / GISCO, © EuroGeographics
    </div>
    '''
    m.get_root().html.add_child(folium.Element(attribution_html))

    # Save
    m.save(save_path)
