# Database Structure

This application uses a split-database architecture:

## regions.db (144 MB - Included in releases)
**Read-only reference data** - Pre-loaded on app startup

Contains:
- 97,987 LAU regions (Local Administrative Units) with geometry
- 1,798 NUTS regions (levels 0-3) with geometry
- 98,647 LAU-NUTS mappings

This database is generated once and can be distributed with the application.

**Data License Notice:**
The geospatial data in this database is sourced from Eurostat/GISCO and is subject to separate licensing terms. See the [LICENSE](../LICENSE) file for complete attribution and usage requirements.

**Required Attribution:**
> © European Commission – Eurostat / GISCO, and © EuroGeographics where applicable.

## user.db (User-specific)
**User activity data** - Created on first run

Contains:
- Your Strava activities
- Authentication tokens
- Activity-region links
- Settings

This database is stored in your local application data folder and is never shared.

## Why Split?

1. **Small executables**: App can be ~10MB without bundling regions
2. **Easy updates**: Region data can be updated independently
3. **Data safety**: Your activity data is separate from app code
4. **Multi-user**: Multiple users can have separate user databases
5. **Privacy**: User data never mixed with reference data
