# Project Structure

```
stravagonuts/
├── stravagonuts/              # Main application package
│   ├── __init__.py            # Package initialization, exports create_app()
│   ├── app.py                 # Flask application and routes
│   ├── database.py            # Database operations
│   ├── strava_service.py      # Strava API integration
│   ├── map_generator.py       # Map generation
│   ├── nuts_handler.py        # NUTS data handling
│   ├── region_database_init.py # Region database setup
│   ├── templates/             # Flask templates
│   └── static/                # Static assets
├── databases/                 # Database files (data)
│   ├── regions.db             # Reference data (bundled for releases)
│   ├── user.db                # User data (gitignored)
│   └── README.md              # Database documentation
├── run.py                     # Entry point for running from source
├── reset.py                   # Utility script for resetting data
├── requirements.txt           # Python dependencies
├── README.md                  # Project documentation
├── LICENSE                    # MIT + Data attribution
└── .gitignore                 # Git ignore rules
```

## Package Structure Benefits

### For Development (running from source):
```bash
python run.py
```

### For PyInstaller Executable:
```bash
pyinstaller --name StravaGoNuts \
    --onefile \
    --add-data "stravagonuts/templates:stravagonuts/templates" \
    --add-data "stravagonuts/static:stravagonuts/static" \
    --add-data "databases/regions.db:databases" \
    --hidden-import shapely.geometry \
    --hidden-import geopandas \
    run.py
```

### For Docker:
```dockerfile
COPY stravagonuts/ /app/stravagonuts/
COPY run.py requirements.txt /app/
RUN pip install -r requirements.txt
CMD ["python", "run.py"]
```

## Key Design Decisions

1. **Package Structure**: All application code in `stravagonuts/` package with relative imports
2. **Entry Point Separation**: `run.py` handles initialization, package handles logic
3. **Data Separation**: `databases/` at root level, separate from code
4. **Utility Scripts**: `reset.py` at root for easy access
5. **Factory Pattern**: `create_app()` function for flexible app initialization
