# IHME Data Lakehouse — Data Catalog

All datasets are available in both **CSV** (universal) and **Parquet** (fast, typed) formats.

## Quick Start

```python
import pandas as pd

# Load any dataset
deaths = pd.read_csv("datasets/gbd2023_deaths_204countries_1990_2023.csv")
# or for faster loading:
deaths = pd.read_parquet("datasets/gbd2023_deaths_204countries_1990_2023.parquet")

# Combined burden (Deaths + DALYs + YLLs + YLDs in one file)
burden = pd.read_parquet("datasets/gbd2023_all_burden_204countries_1990_2023.parquet")
```

## Datasets

### GBD 2023 Cause-Level Burden (204 countries, 1990-2023)

| File | Rows | Description |
|------|------|-------------|
| `gbd2023_deaths_204countries_1990_2023` | 13,872 | All-cause mortality (number + rate) |
| `gbd2023_dalys_204countries_1990_2023` | 13,872 | Disability-adjusted life years |
| `gbd2023_ylls_204countries_1990_2023` | 13,872 | Years of life lost |
| `gbd2023_ylds_204countries_1990_2023` | 13,872 | Years lived with disability |
| `gbd2023_all_burden_204countries_1990_2023` | 55,488 | All four measures combined |

**Columns:** `location_id`, `location`, `year`, `sex`, `age_group`, `cause`, `measure`, `metric`, `value`, `upper`, `lower`

### Population

| File | Rows | Description |
|------|------|-------------|
| `gbd2023_population_204countries_1990_2023` | 20,808 | Population estimates (Male, Female, Both) |

**Columns:** `location_id`, `location`, `year`, `sex`, `age_group`, `metric`, `value`, `upper`, `lower`

### Socio-Demographic Index (SDI)

| File | Rows | Description |
|------|------|-------------|
| `gbd2021_sdi_1950_2021` | 52,992 | SDI values for all GBD locations |

**Columns:** `location_id`, `location`, `year`, `sex`, `age_group`, `sdi`, `sdi_lower`, `sdi_upper`

## Data Sources

- **GBD 2023 Results:** Downloaded via [GBD Results Tool](https://vizhub.healthdata.org/gbd-results/) (version 8352)
- **SDI:** Downloaded from [GHDx](https://ghdx.healthdata.org/gbd-2021) Files tab
- All data is freely available from [IHME/GHDx](https://ghdx.healthdata.org/) (requires free account)

## Citation

Institute for Health Metrics and Evaluation (IHME). *Global Burden of Disease Study 2023 (GBD 2023) Results.* Seattle, United States: IHME, 2025.
