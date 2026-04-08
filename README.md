# IHME Data Lakehouse

Registry-driven pipeline for [IHME Global Burden of Disease](https://ghdx.healthdata.org/) data. Downloads, validates, and transforms GBD data into clean, analysis-ready datasets.

## Ready-to-Use Data

The `datasets/` folder contains clean CSV and Parquet files ready for analysis:

```python
import pandas as pd

# All-cause mortality for 204 countries, 1990-2023
deaths = pd.read_csv("datasets/gbd2023_deaths_204countries_1990_2023.csv")

# Combined burden (Deaths + DALYs + YLLs + YLDs)
burden = pd.read_parquet("datasets/gbd2023_all_burden_204countries_1990_2023.parquet")

# Population estimates
pop = pd.read_parquet("datasets/gbd2023_population_204countries_1990_2023.parquet")

# Socio-Demographic Index
sdi = pd.read_parquet("datasets/gbd2021_sdi_1950_2021.parquet")
```

See [`datasets/DATA_CATALOG.md`](datasets/DATA_CATALOG.md) for full documentation.

### Available Datasets

| Dataset | Rows | Years | Coverage |
|---------|------|-------|----------|
| Deaths | 13,872 | 1990-2023 | 204 countries, all-cause |
| DALYs | 13,872 | 1990-2023 | 204 countries, all-cause |
| YLLs | 13,872 | 1990-2023 | 204 countries, all-cause |
| YLDs | 13,872 | 1990-2023 | 204 countries, all-cause |
| Population | 20,808 | 1990-2023 | 204 countries, M/F/Both |
| CVD | 8,736 | 1980-2023 | 13 regions, deaths |
| SDI | 52,992 | 1950-2021 | All GBD locations |
| **Combined burden** | **55,488** | **1990-2023** | **All 4 measures** |

## Pipeline Architecture

```
raw/          → bronze/         → silver/          → datasets/
(downloads)    (provenance)      (parquet, typed)    (clean CSV+Parquet)
```

Six data domains: `gbd_results`, `gbd_risk`, `gbd_covariates`, `population`, `forecasts`, `specialty`

### CLI

```bash
pip install -e .

ihme-data status                    # Pipeline status for all domains
ihme-data registry-list             # List registered download URLs
ihme-data fetch --all               # Download from registry
ihme-data promote --all             # Promote raw → bronze → silver
ihme-data catalog                   # Build searchable catalog
ihme-data search "mortality"        # Search the catalog
```

### Data Sources

- **GBD 2023 Results:** Via [GBD Results Tool](https://vizhub.healthdata.org/gbd-results/) (API version 8352)
- **SDI/Covariates:** Direct download from [GHDx](https://ghdx.healthdata.org/gbd-2021) file pages
- **Demographics & Forecasts:** GHDx appendix tables

All data requires a free [GHDx account](https://ghdx.healthdata.org/download-access/login).

## Project Structure

```
ihme-data-lakehouse/
├── datasets/              # Clean, ready-to-use CSV + Parquet files
│   ├── DATA_CATALOG.md
│   ├── gbd2023_deaths_*.csv/.parquet
│   ├── gbd2023_dalys_*.csv/.parquet
│   ├── gbd2023_ylls_*.csv/.parquet
│   ├── gbd2023_ylds_*.csv/.parquet
│   ├── gbd2023_population_*.csv/.parquet
│   ├── gbd2023_all_burden_*.csv/.parquet
│   └── gbd2021_sdi_*.csv/.parquet
├── registry/              # Download URLs + checksums
│   └── sources.yaml
├── src/ihme_data_lakehouse/
│   ├── cli.py             # CLI entry point
│   ├── config.py          # Paths and constants
│   ├── http.py            # Download engine with retry
│   ├── normalize.py       # Type coercion + harmonization
│   ├── promote/           # Domain-specific raw→silver modules
│   ├── registry.py        # YAML registry loader
│   ├── catalog.py         # Searchable data catalog
│   └── storage.py         # Manifest writer
├── scripts/
│   └── export_datasets.py # Regenerate datasets/ from silver
├── tests/                 # 39 tests
└── pyproject.toml
```

## Citation

Institute for Health Metrics and Evaluation (IHME). *Global Burden of Disease Study 2023 (GBD 2023) Results.* Seattle, United States: IHME, 2025.

## License

Data is provided by IHME under their [data use agreement](https://www.healthdata.org/data-tools-practices/data-access). Pipeline code is MIT.
