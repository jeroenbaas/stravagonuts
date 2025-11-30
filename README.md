# Strava Go NUTS

Map your Strava activities across European administrative regions (LAU and NUTS levels).

## Features

- **OAuth Integration**: Seamless Strava authentication through your browser
- **Multi-Level Region Tracking**: Track activities across 5 administrative levels:
  - LAU (Local Administrative Units) - finest granularity
  - NUTS 0, 1, 2, 3 (Nomenclature of Territorial Units for Statistics)
- **Interactive Maps**: View your activities on interactive OpenStreetMap-based maps
- **Region Statistics**: See which regions you've visited, activity counts, and first visit dates
- **Automatic Processing**: Auto-fetches GPS data and regenerates maps when needed
- **Real-Time Progress**: Live progress updates during data processing

## Requirements

- Python 3.7+
- Strava API credentials (Client ID and Secret)

## Installation

1. Clone the repository:
```bash
git clone git@github.com:jeroenbaas/stravagonuts.git
cd stravagonuts
```

2. Create a virtual environment (recommended):
```bash
python3 -m venv venv
source venv/bin/activate
```

3. Install dependencies:
```bash
pip install -r requirements.txt
```

4. Run the application:
```bash
python run.py
```

## First-Time Setup

You will be guided through below steps in the application itself: 

1. Go to [Strava API Settings](https://www.strava.com/settings/api)
2. Create a new application
3. Set **Authorization Callback Domain** to: `localhost`
4. Copy your **Client ID** and **Client Secret**
5. Enter them in the setup page when first running the app
6. Authorize the application to access your activities

## How It Works

1. **Startup**: Downloads and indexes all EU LAU and NUTS region data
2. **Authorization**: OAuth flow to connect your Strava account
3. **Activity Sync**: Fetches your activities incrementally (200 per page)
4. **GPS Processing**: Downloads GPS streams for activities
5. **Region Matching**: Matches GPS tracks to administrative regions
6. **Map Generation**: Creates interactive maps for all 5 levels

## Data Sources

- **LAU Regions**: [Eurostat GISCO - LAU 2024](https://ec.europa.eu/eurostat/web/gisco/geodata/reference-data/administrative-units-statistical-units/lau)
- **NUTS Regions**: [Eurostat GISCO - NUTS 2024](https://ec.europa.eu/eurostat/web/gisco/geodata/reference-data/administrative-units-statistical-units/nuts)
- **LAU-NUTS Mapping**: [Eurostat LAU-NUTS 2024 Correspondence](https://ec.europa.eu/eurostat/web/nuts/correspondence-tables)

## Reset Options

Use `reset.py` to clear data; you can also do this within the app.

```bash
python reset.py
```

Options:
1. **All data**: Complete reset (database, maps, cached shapefiles)
2. **User data**: Clear activities/auth but keep region database
3. **Map data**: Regenerate maps only
4. **Region database**: Reload region data (useful for updates)

## Architecture

- **Flask**: Web server with OAuth integration
- **SQLite**: Local database for activities, regions, and mappings
- **GeoPandas**: Spatial data processing
- **Folium**: Interactive map generation
- **OpenStreetMap**: Base map tiles

## License

This project is licensed under the MIT License - see the [LICENSE](LICENSE) file for details.

### Geospatial Data Attribution

**Important:** The administrative boundary data (NUTS & LAU) is **NOT** covered by the MIT license.

The geospatial datasets used in this project are sourced from:
- **© European Commission – Eurostat / GISCO**
- **© EuroGeographics** (where applicable)

These datasets are redistributed under the terms specified by their original providers. See the [LICENSE](LICENSE) file for complete terms and conditions regarding the use, modification, and redistribution of boundary data.

**Required Attribution:**
> © European Commission – Eurostat / GISCO, and © EuroGeographics where applicable.

For full legal terms, consult:
- [Eurostat Copyright Policy](https://ec.europa.eu/eurostat/about/policies/copyright)
- [GISCO Data Policy](https://ec.europa.eu/eurostat/web/gisco/geodata/reference-data)
