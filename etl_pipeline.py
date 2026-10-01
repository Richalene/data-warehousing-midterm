"""Load Group 3's hospital dataset into SQLite and optional MongoDB.

The source has no real admission, department, date, or clinical note fields.
Encounter IDs are warehouse row keys, and service lines are derived analytical
categories. MongoDB stores source-backed encounter context, not clinical notes.
"""

import argparse
import json
import sqlite3
from pathlib import Path

import pandas as pd


ROOT = Path(__file__).resolve().parent
SERVICE_LINES = {
    "Heart Disease": "Cardiovascular", "Heart Attack": "Cardiovascular",
    "Hypertension": "Cardiovascular", "Stroke": "Neurology",
    "Diabetes": "Metabolic", "Fractured Arm": "Orthopedics",
    "Fractured Leg": "Orthopedics", "Osteoarthritis": "Orthopedics",
    "Cancer": "Oncology", "Prostate Cancer": "Oncology",
    "Respiratory Infection": "Respiratory", "Appendicitis": "General surgery",
    "Kidney Stones": "Urology", "Childbirth": "Obstetrics",
    "Allergic Reaction": "Allergy and immunology",
}


def clean(source: Path):
    data = pd.read_csv(source, dtype={"Patient_ID": "string"})
    required = {"Patient_ID", "Age", "Gender", "Condition", "Procedure", "Cost",
                "Length_of_Stay", "Readmission", "Outcome", "Satisfaction"}
    missing = required - set(data.columns)
    if missing:
        raise ValueError(f"Missing columns: {sorted(missing)}")
    stats = {"source_rows": len(data)}
    data["Patient_ID"] = data["Patient_ID"].str.strip().replace("", pd.NA)
    data = data.dropna(subset=["Patient_ID"]).copy()
    stats["missing_patient_ids_removed"] = stats["source_rows"] - len(data)
    data["Cost"] = pd.to_numeric(data["Cost"].astype("string").str.replace(r"[$,]", "", regex=True), errors="coerce")
    invalid = data["Cost"].isna() | data["Cost"].lt(0)
    stats["invalid_costs_removed"] = int(invalid.sum())
    data = data.loc[~invalid].copy()
    data["Length_of_Stay"] = pd.to_numeric(data["Length_of_Stay"], errors="coerce")
    invalid_los = data["Length_of_Stay"].isna() | data["Length_of_Stay"].lt(0)
    stats["invalid_stays_removed"] = int(invalid_los.sum())
    data = data.loc[~invalid_los].copy()
    data = data.drop_duplicates().reset_index(drop=True)
    stats["duplicate_rows_removed"] = stats["source_rows"] - stats["missing_patient_ids_removed"] - stats["invalid_costs_removed"] - stats["invalid_stays_removed"] - len(data)
    data["service_line"] = data["Condition"].map(SERVICE_LINES).fillna("Other / unmapped")
    stats["loaded_rows"] = len(data)
    stats["unmapped_conditions"] = int((data["service_line"] == "Other / unmapped").sum())
    return data, stats


def load_sqlite(data, path: Path):
    if path.exists():
        path.unlink()  # rebuild is deterministic; avoid duplicating encounters
    with sqlite3.connect(path) as db:
        db.execute("PRAGMA foreign_keys = ON")
        db.executescript("""
        CREATE TABLE dim_patient (
            patient_key INTEGER PRIMARY KEY, source_patient_id TEXT UNIQUE NOT NULL,
            age INTEGER, gender TEXT
        );
        CREATE TABLE dim_condition (condition_key INTEGER PRIMARY KEY, condition_name TEXT UNIQUE NOT NULL);
        CREATE TABLE dim_procedure (procedure_key INTEGER PRIMARY KEY, procedure_name TEXT UNIQUE NOT NULL);
        CREATE TABLE dim_service_line (
            service_line_key INTEGER PRIMARY KEY, service_line_name TEXT UNIQUE NOT NULL,
            is_derived INTEGER NOT NULL DEFAULT 1
        );
        CREATE TABLE fact_encounter (
            encounter_key INTEGER PRIMARY KEY, patient_key INTEGER NOT NULL,
            condition_key INTEGER NOT NULL, procedure_key INTEGER NOT NULL,
            service_line_key INTEGER NOT NULL, cost NUMERIC NOT NULL CHECK(cost >= 0),
            length_of_stay INTEGER NOT NULL CHECK(length_of_stay >= 0),
            readmission TEXT, outcome TEXT, satisfaction INTEGER,
            FOREIGN KEY(patient_key) REFERENCES dim_patient(patient_key),
            FOREIGN KEY(condition_key) REFERENCES dim_condition(condition_key),
            FOREIGN KEY(procedure_key) REFERENCES dim_procedure(procedure_key),
            FOREIGN KEY(service_line_key) REFERENCES dim_service_line(service_line_key)
        );
        CREATE INDEX idx_fact_service_line ON fact_encounter(service_line_key);
        CREATE INDEX idx_fact_condition ON fact_encounter(condition_key);
        """)
        # Each distinct source ID is one patient. An encounter key is one CSV row.
        patients = data.drop_duplicates("Patient_ID")[['Patient_ID', 'Age', 'Gender']]
        db.executemany("INSERT INTO dim_patient(source_patient_id,age,gender) VALUES(?,?,?)",
                       [(str(p), int(a), str(g)) for p, a, g in patients.itertuples(index=False, name=None)])
        for table, column, values in (
            ("dim_condition", "condition_name", data["Condition"]),
            ("dim_procedure", "procedure_name", data["Procedure"]),
            ("dim_service_line", "service_line_name", data["service_line"]),
        ):
            db.executemany(f"INSERT INTO {table}({column}) VALUES(?)", [(str(v),) for v in sorted(values.unique())])
        def lookup(table, key, label):
            return dict(db.execute(f"SELECT {label}, {key} FROM {table}"))
        patient = lookup("dim_patient", "patient_key", "source_patient_id")
        condition = lookup("dim_condition", "condition_key", "condition_name")
        procedure = lookup("dim_procedure", "procedure_key", "procedure_name")
        service = lookup("dim_service_line", "service_line_key", "service_line_name")
        rows = []
        for r in data.itertuples(index=False):
            rows.append((patient[str(r.Patient_ID)], condition[r.Condition], procedure[r.Procedure],
                         service[r.service_line], float(r.Cost), int(r.Length_of_Stay),
                         str(r.Readmission), str(r.Outcome), int(r.Satisfaction)))
        db.executemany("""INSERT INTO fact_encounter
            (patient_key, condition_key, procedure_key, service_line_key, cost,
             length_of_stay, readmission, outcome, satisfaction)
            VALUES (?,?,?,?,?,?,?,?,?)""", rows)
        violations = db.execute("PRAGMA foreign_key_check").fetchall()
        if violations:
            raise RuntimeError(f"Foreign key violations: {violations[:5]}")
        print(f"SQLite: {len(rows)} encounters, {len(patient)} patients, {len(condition)} conditions, {len(service)} derived service lines")


def documents(data):
    for i, r in enumerate(data.itertuples(index=False), start=1):
        yield {"_id": i, "source_patient_id": str(r.Patient_ID), "condition": r.Condition,
               "procedure": r.Procedure, "service_line_derived": r.service_line,
               "outcome": r.Outcome, "readmission": r.Readmission,
               "length_of_stay": int(r.Length_of_Stay), "cost": float(r.Cost),
               "record_type": "source_backed_encounter_context", "clinical_note_available": False}


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=ROOT / "hospital data analysis(1).csv")
    parser.add_argument("--mongo-uri", default=None, help="Optional MongoDB URI, e.g. mongodb://localhost:27017")
    args = parser.parse_args()
    data, stats = clean(args.source)
    for name, count in stats.items():
        print(f"{name}: {count}")
    load_sqlite(data, ROOT / "warehouse.db")
    docs = list(documents(data))
    with (ROOT / "encounter_context.jsonl").open("w", encoding="utf-8") as out:
        for doc in docs:
            out.write(json.dumps(doc, ensure_ascii=False) + "\n")
    print(f"Document export: {len(docs)} source-backed records -> encounter_context.jsonl")
    if args.mongo_uri:
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise SystemExit("MongoDB requested: install pymongo with pip install -r requirements.txt") from exc
        client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=3000)
        client.admin.command("ping")
        collection = client.group3_healthcare.encounter_context
        collection.delete_many({})
        collection.insert_many(docs)
        print(f"MongoDB: {collection.count_documents({})} documents loaded in group3_healthcare.encounter_context")
        client.close()
    else:
        print("MongoDB: NOT EXECUTED (pass --mongo-uri with a running server)")


if __name__ == "__main__":
    main()
