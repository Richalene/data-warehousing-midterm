# Group 3 - Healthcare Patient Encounter & Treatment Cost Warehouse

## Run

From this directory, with Python 3.10+:

```bash
python -m pip install -r requirements.txt
python etl_pipeline.py > milestone1_log.txt
python olap_analysis.py > olap_output.txt
python make_report.py
```

To populate MongoDB and run the `$facet` query, start a local MongoDB server and run:

```bash
python etl_pipeline.py --mongo-uri mongodb://localhost:27017 > milestone1_log.txt
python olap_analysis.py --mongo-uri mongodb://localhost:27017 > olap_output.txt
```

The included logs were captured in an environment without MongoDB. Re-run the two commands above to obtain proof of a real MongoDB load and query, then take screenshots of your own terminal for the Teams requirement. The Mongo collection is `group3_healthcare.encounter_context`. The JSONL file is a portable export of the same documents.

## Dataset limits and meaning

- The source has 984 rows and columns for `Patient_ID`, age, gender, condition, procedure, cost, length of stay, readmission, outcome, and satisfaction. The cleaned CSV matches the raw file for this sample. No invalid rows were found.
- There is no admission ID: `encounter_key` is a generated row key. `Patient_ID` is the source ID. One row is treated as one encounter; there is no evidence of repeat admissions by the same patient in this sample.
- There is no hospital department. `dim_service_line` is a documented mapping from **condition** to an **analytical service line**, not an observed department. This proxy supports comparisons but cannot establish actual department performance.
- There are no admission or discharge dates. Length of stay is taken directly from the source; no monthly trend is possible.
- There are no clinical notes. MongoDB contains source-backed encounter context documents, with `clinical_note_available: false`; these must not be presented as original clinical notes. Obtain a real notes source to meet that specific requirement.
- `Cost` has no stated currency or unit in the dataset; all totals are in source cost units.
- The records may be synthetic or unusually patterned. Do not use findings to make clinical decisions.

## Files

`etl_pipeline.py` validates and cleans the input, rebuilds a small star schema in `warehouse.db`, and exports MongoDB-ready documents. `olap_analysis.py` runs a CTE, `DENSE_RANK`, cumulative `SUM OVER`, `LAG`, and optional MongoDB `$facet`. `Data_Cleaner.py` is the original Part 1 script supplied by the group. Its hard-coded input filename differs from the actual uploaded filename; the integrated ETL uses the actual filename. The PDF summarizes verified SQLite results and caveats.
