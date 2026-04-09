# IHME Data Lakehouse — Progress (2026-04-09)

## Bulk GHDx Download Pipeline

### Completed
- [x] Scraped all 10 pages of GHDx catalog → 482 datasets
- [x] Scraped all 482 record pages with authentication → 2,187 file URLs
- [x] Automated Azure B2C login via Selenium (headless)
- [x] Download pipeline running (sequential, resumable)
- [x] Organizer script classifying files into lakehouse domains

### In Progress
- [ ] Downloading 2,187 files (currently ~2 GB / 34 files of 2,187)
- [ ] Covariates SEV_SCALAR files are very large (~200 MB each)

### Domain Classification
| Domain | Description |
|--------|-------------|
| gbd_results | Cause-specific mortality, DALYs, burden estimates |
| gbd_covariates | SDI, covariates, disability weights |
| gbd_risk | Risk exposures, air pollution, smoking, water/sanitation |
| population | Demographics, fertility, life expectancy |
| forecasts | Health spending, mortality, disease forecasts |
| health_financing | Health spending, DAH, GDP, inefficiency |
| vaccination | Coverage estimates, RSV, measles |
| us_subnational | US county-level mortality/HALE by race/ethnicity |
| reference | ICD codes, cause/REI/location hierarchies |
| specialty | Disease-specific (diabetes, RHD, HIV, suicide, etc.) |

### Key Files
- `registry/ghdx_catalog.json` — 482 dataset metadata
- `registry/ghdx_files_auth.json` — 2,187 authenticated file URLs
- `registry/download_progress.json` — resumable download tracker
- `registry/organized_manifest.json` — domain classification manifest

### Scripts
- `scripts/scrape_ghdx_catalog.py` — catalog scraper (public, no auth)
- `scripts/scrape_record_files.py` — record page scraper (no auth)
- `scripts/full_pipeline.py` — login + scrape + download (main pipeline)
- `scripts/organize_bulk_downloads.py` — classify into lakehouse domains

### Resume After Interruption
```bash
# Re-run pipeline (skips completed downloads automatically)
python scripts/full_pipeline.py "EMAIL" "PASSWORD"

# Or just re-organize already-downloaded files
python scripts/organize_bulk_downloads.py --copy
```

### Blockers
- 1 file failed (connection broken): Covariate Files SEV_DIET_VEG (retry on next run)
- Location crosswalk (location_id → ISO-3) still missing for harmonized layer
