import os
import requests
import zipfile



# URLs for NUTS data
NUTS_MAPPING_URL = "https://ec.europa.eu/eurostat/documents/345175/501971/EU-27-LAU-2024-NUTS-2024.xlsx"
NUTS_SHAPEFILE_URL = "https://gisco-services.ec.europa.eu/distribution/v2/nuts/shp/NUTS_RG_60M_2024_3035.shp.zip"

# Data directories
NUTS_DATA_DIR = "nuts_data"
NUTS_MAPPING_FILE = os.path.join(NUTS_DATA_DIR, "lau_nuts_mapping.xlsx")
NUTS_SHAPEFILE_DIR = os.path.join(NUTS_DATA_DIR, "shp")


def download_nuts_mapping():
    """Download the LAU to NUTS mapping Excel file."""
    os.makedirs(NUTS_DATA_DIR, exist_ok=True)

    if os.path.exists(NUTS_MAPPING_FILE):
        print("[NUTS] Mapping file already exists")
        return NUTS_MAPPING_FILE

    print("[NUTS] Downloading LAU to NUTS mapping file...")
    response = requests.get(NUTS_MAPPING_URL)
    response.raise_for_status()

    with open(NUTS_MAPPING_FILE, "wb") as f:
        f.write(response.content)

    print(f"[NUTS] Mapping file downloaded to {NUTS_MAPPING_FILE}")
    return NUTS_MAPPING_FILE


def parse_nuts_mapping():
    """Parse the LAU to NUTS mapping Excel file."""
    mapping_file = download_nuts_mapping()

    print("[NUTS] Parsing LAU to NUTS mapping...")

    # Read all sheet names
    import pandas as pd
    excel_file = pd.ExcelFile(mapping_file)
    sheet_names = excel_file.sheet_names

    # Filter for 2-character country code sheets
    country_sheets = [s for s in sheet_names if len(s) == 2 and s.isalpha() and s.isupper()]

    print(f"[NUTS] Found {len(country_sheets)} country sheets: {', '.join(country_sheets)}")

    # Parse all country sheets
    all_mappings = []

    for sheet in country_sheets:
        try:
            df = pd.read_excel(mapping_file, sheet_name=sheet)

            # Look for columns with NUTS and LAU codes
            # We want: 'NUTS 3 CODE' and 'EU LAU CODE' (which has country prefix)
            nuts_col = None
            eu_lau_col = None

            for col in df.columns:
                col_str = str(col).upper()
                if 'NUTS' in col_str and '3' in col_str:
                    nuts_col = col
                elif 'EU' in col_str and 'LAU' in col_str:
                    eu_lau_col = col

            if nuts_col is None or eu_lau_col is None:
                print(f"[NUTS] Warning: Could not find NUTS3/EU LAU CODE columns in sheet {sheet}")
                print(f"[NUTS] Available columns: {list(df.columns)}")
                continue

            # Extract mapping using EU LAU CODE (which has country prefix like "BE_21001")
            mapping_df = df[[nuts_col, eu_lau_col]].copy()
            mapping_df.columns = ['NUTS3_CODE', 'LAU_CODE']
            mapping_df['COUNTRY'] = sheet

            # Drop NaN values
            mapping_df = mapping_df.dropna()

            all_mappings.append(mapping_df)
            print(f"[NUTS] Parsed {len(mapping_df)} mappings from {sheet}")

        except Exception as e:
            print(f"[NUTS] Error parsing sheet {sheet}: {e}")
            continue

    if not all_mappings:
        raise RuntimeError("No valid country mappings found in Excel file")

    # Combine all mappings
    full_mapping = pd.concat(all_mappings, ignore_index=True)

    # Derive NUTS0, NUTS1, NUTS2 from NUTS3
    full_mapping['NUTS0_CODE'] = full_mapping['NUTS3_CODE'].str[:2]
    full_mapping['NUTS1_CODE'] = full_mapping['NUTS3_CODE'].str[:3]
    full_mapping['NUTS2_CODE'] = full_mapping['NUTS3_CODE'].str[:4]

    print(f"[NUTS] Total mappings: {len(full_mapping)}")

    return full_mapping


def download_nuts_shapefile():
    """Download and extract NUTS shapefile."""
    os.makedirs(NUTS_DATA_DIR, exist_ok=True)
    zip_path = os.path.join(NUTS_DATA_DIR, "NUTS_2024.zip")

    if not os.path.exists(zip_path):
        print("[NUTS] Downloading NUTS shapefile...")
        response = requests.get(NUTS_SHAPEFILE_URL)
        response.raise_for_status()
        with open(zip_path, "wb") as f:
            f.write(response.content)
        print(f"[NUTS] Downloaded to {zip_path}")

    if not os.path.exists(NUTS_SHAPEFILE_DIR):
        print("[NUTS] Extracting NUTS shapefile...")
        os.makedirs(NUTS_SHAPEFILE_DIR, exist_ok=True)
        with zipfile.ZipFile(zip_path, "r") as z:
            z.extractall(NUTS_SHAPEFILE_DIR)
        print(f"[NUTS] Extracted to {NUTS_SHAPEFILE_DIR}")

    # Find the .shp file
    for root, _, files in os.walk(NUTS_SHAPEFILE_DIR):
        for file in files:
            if file.endswith(".shp"):
                shp_path = os.path.join(root, file)
                print(f"[NUTS] Found shapefile: {shp_path}")
                return shp_path

    raise FileNotFoundError("Could not locate NUTS .shp file after extracting")


def load_nuts_shapefile():
    """Load NUTS shapefile as GeoDataFrame."""
    shp_path = download_nuts_shapefile()

    print("[NUTS] Loading NUTS shapefile...")
    import geopandas as gpd
    nuts_gdf = gpd.read_file(shp_path)

    # Standardize column names
    if 'NUTS_ID' in nuts_gdf.columns:
        nuts_gdf = nuts_gdf.rename(columns={'NUTS_ID': 'NUTS_CODE'})

    print(f"[NUTS] Loaded {len(nuts_gdf)} NUTS regions")
    print(f"[NUTS] Columns: {list(nuts_gdf.columns)}")

    return nuts_gdf


def get_nuts_level(nuts_code):
    """Determine NUTS level from code (0, 1, 2, or 3)."""
    return len(nuts_code) - 2 if len(nuts_code) >= 2 else None


def filter_nuts_by_level(nuts_gdf, level):
    """Filter NUTS GeoDataFrame by level (0, 1, 2, or 3)."""
    if 'LEVL_CODE' in nuts_gdf.columns:
        return nuts_gdf[nuts_gdf['LEVL_CODE'] == level].copy()
    else:
        # Fallback: filter by code length
        target_length = 2 + level
        return nuts_gdf[nuts_gdf['NUTS_CODE'].str.len() == target_length].copy()
