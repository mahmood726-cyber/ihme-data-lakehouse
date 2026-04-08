"""Master catalog builder: scans silver layer and builds a unified dataset index."""
from __future__ import annotations
from pathlib import Path
import pandas as pd

DESCRIPTION_HINTS = {
    "gbd_results": "GBD cause-level results",
    "gbd_risk": "GBD risk factor attributable burden",
    "gbd_covariates": "GBD covariates (SDI, HAQ, etc.)",
    "population": "IHME population estimates",
    "forecasts": "GBD Foresight projections",
    "specialty": "Specialty datasets (IGME, AMR, etc.)",
}

def build_catalog(silver_dir: Path, output_path: Path | None = None) -> pd.DataFrame:
    """Scan silver/ for all parquet files and build a unified catalog."""
    rows: list[dict] = []
    for domain_dir in sorted(silver_dir.iterdir()):
        if not domain_dir.is_dir():
            continue
        domain = domain_dir.name
        hint = DESCRIPTION_HINTS.get(domain, domain)
        for tier_dir in sorted(domain_dir.iterdir()):
            if not tier_dir.is_dir():
                continue
            tier = tier_dir.name
            for pq in sorted(tier_dir.glob("*.parquet")):
                df = pd.read_parquet(pq)
                rows.append({
                    "domain": domain,
                    "tier": tier,
                    "dataset": pq.stem,
                    "description": f"{hint}: {pq.stem} ({tier})",
                    "rows": len(df),
                    "columns": len(df.columns),
                    "column_names": ", ".join(df.columns[:20]),
                    "silver_path": str(pq),
                })
    catalog = pd.DataFrame.from_records(rows)
    if catalog.empty:
        catalog = pd.DataFrame(columns=["domain", "tier", "dataset", "description", "rows", "columns", "column_names", "silver_path"])
    catalog = catalog.sort_values(["domain", "tier", "dataset"]).reset_index(drop=True)
    if output_path is not None:
        output_path.parent.mkdir(parents=True, exist_ok=True)
        catalog.to_parquet(output_path, index=False)
    return catalog

def search_catalog(catalog: pd.DataFrame, keyword: str | None = None, domain: str | None = None, tier: str | None = None) -> pd.DataFrame:
    """Filter catalog by keyword, domain, and/or tier."""
    mask = pd.Series(True, index=catalog.index)
    if domain is not None:
        mask &= catalog["domain"].str.lower() == domain.lower()
    if tier is not None:
        mask &= catalog["tier"].str.lower() == tier.lower()
    if keyword is not None:
        kw = keyword.lower()
        text_match = (
            catalog["dataset"].str.lower().str.contains(kw, na=False)
            | catalog["description"].str.lower().str.contains(kw, na=False)
            | catalog["column_names"].str.lower().str.contains(kw, na=False)
        )
        mask &= text_match
    return catalog.loc[mask].reset_index(drop=True)
