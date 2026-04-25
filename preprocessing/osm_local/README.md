# OSM local data extraction

Notebooks for extracting OSM features (highways, etc.) from Geofabrik PBF downloads into GeoPackages and GEE-ready CSVs.

## Environment setup

> **Important:** Python processing for OSM extraction should be carried out in a **Conda virtual environment**, not Pip.
>
> Specifically, `pyosmium` (the local-extraction package used for reading Geofabrik PBF files) has only been reliably installable via Conda in our testing. Pip installations of `pyosmium` failed or produced incomplete builds on Windows.

### Suggested conda env

```bash
conda create -n osm-pff python=3.11
conda activate osm-pff
conda install -c conda-forge pyosmium geopandas pandas shapely
```

Other OSM-related folders (`osm_online/`, `microsoft/`, `wdb/`) may have different requirements — but the Conda/pyosmium recommendation applies wherever `osmium.SimpleHandler` is used for local PBF parsing.

## Notebook order

1. [`osm_local_data_1_extract_flexible.ipynb`](osm_local_data_1_extract_flexible.ipynb) — extract OSM features by tag from a PBF to a GeoPackage
2. [`osm_local_data_2a_gpkg_to_csvs.ipynb`](osm_local_data_2a_gpkg_to_csvs.ipynb) — split large GeoPackages into chunked CSVs with WKT (for GEE upload)
3. [`osm_local_data_2b_combine_csvs_small_to_large.ipynb`](osm_local_data_2b_combine_csvs_small_to_large.ipynb) — combine/reassemble CSV chunks
4. Supporting: [`removing_unwanted_tags.ipynb`](removing_unwanted_tags.ipynb), [`renaming_files.ipynb`](renaming_files.ipynb)

See also: [`old_osm_local_data_1_batch_extract_highways.ipynb`](old_osm_local_data_1_batch_extract_highways.ipynb) for the earlier batch-extract approach.

## Conventions

- Binary classification: 1 = presence, 0 = absence
- Geometry format: WKT for GEE compatibility
- Chunk size default: 10,000 rows
- Naming convention: `{prefix}_{start_idx}_to_{end_idx}_of_{total_rows}.csv`
