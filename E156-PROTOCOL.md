# E156 Protocol — IHME Data Lakehouse

**Project:** IHME Data Lakehouse
**Date Created:** 2026-04-08
**Date Last Updated:** 2026-04-08
**Workbook Entry:** [TBD — to be assigned after adding to rewrite-workbook.txt]

## E156 Body (CURRENT BODY)

What coverage does IHME's Global Burden of Disease data achieve when systematically catalogued through an automated lakehouse pipeline? We process six GBD data domains — cause-level results, risk factor attribution, covariates, population estimates, forecasts, and specialty datasets — spanning 369 diseases, 87 risk factors, and 204 countries from 1990 to 2021. A registry-driven Python pipeline fetches bulk CSV exports from known GHDx URLs, validates schemas, and promotes data through bronze and silver tiers preserving IHME's hierarchical coding. The lakehouse yields [N] analysis-ready parquet datasets totalling [X] million rows with dual schema: IHME-native for full fidelity and harmonized (iso3c/year/value) for cross-source joins. Checksums and manifests ensure provenance for [N]% of files fetched via stable URLs. This infrastructure enables reproducible downstream analyses by eliminating ad-hoc data wrangling from IHME's bulk exports. Coverage gaps exist for datasets requiring authenticated GHDx access, which fall back to manual placement.

## Links

- **Repository:** https://github.com/mahmood726-cyber/ihme-data-lakehouse
- **Live Dashboard:** N/A (infrastructure project, no HTML dashboard)
- **Rewrite Workbook:** `C:\E156\rewrite-workbook.txt`
