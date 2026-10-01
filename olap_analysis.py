"""Reproducible SQL OLAP and optional MongoDB facet analysis."""

import argparse
import sqlite3
from pathlib import Path


ROOT = Path(__file__).resolve().parent

SERVICE_LINE_SQL = """
WITH grouped AS (
 SELECT s.service_line_name AS service_line, COUNT(*) AS encounters,
        ROUND(AVG(f.length_of_stay), 2) AS avg_stay_days,
        ROUND(AVG(f.cost), 2) AS avg_cost, ROUND(SUM(f.cost), 2) AS total_cost,
        SUM(CASE WHEN f.readmission = 'Yes' THEN 1 ELSE 0 END) AS readmissions
 FROM fact_encounter f JOIN dim_service_line s USING(service_line_key)
 GROUP BY s.service_line_name
)
SELECT *, ROUND(100.0 * readmissions / encounters, 2) AS readmission_pct,
       DENSE_RANK() OVER (ORDER BY avg_stay_days DESC) AS stay_rank,
       DENSE_RANK() OVER (ORDER BY total_cost DESC) AS spend_rank,
       SUM(total_cost) OVER (ORDER BY total_cost DESC, service_line
          ROWS BETWEEN UNBOUNDED PRECEDING AND CURRENT ROW) AS cumulative_cost_by_spend_rank
FROM grouped ORDER BY avg_stay_days DESC, service_line;
"""

CONDITION_SQL = """
WITH grouped AS (
 SELECT c.condition_name AS condition, s.service_line_name AS service_line,
        COUNT(*) AS encounters, ROUND(AVG(f.length_of_stay), 2) AS avg_stay_days,
        ROUND(SUM(f.cost), 2) AS total_cost
 FROM fact_encounter f JOIN dim_condition c USING(condition_key)
 JOIN dim_service_line s USING(service_line_key)
 GROUP BY c.condition_name, s.service_line_name
)
SELECT *, ROUND(avg_stay_days - LAG(avg_stay_days) OVER
  (PARTITION BY service_line ORDER BY avg_stay_days DESC, condition), 2)
  AS difference_from_previous_condition_days
FROM grouped ORDER BY avg_stay_days DESC, condition;
"""

FACET = [
    {"$facet": {
        "by_service_line": [{"$group": {"_id": "$service_line_derived", "encounters": {"$sum": 1},
                                    "avg_stay_days": {"$avg": "$length_of_stay"},
                                    "total_cost": {"$sum": "$cost"}}},
                            {"$sort": {"avg_stay_days": -1}}],
        "by_outcome": [{"$group": {"_id": "$outcome", "encounters": {"$sum": 1}}},
                       {"$sort": {"encounters": -1}}],
        "by_readmission": [{"$group": {"_id": "$readmission", "encounters": {"$sum": 1}}},
                            {"$sort": {"encounters": -1}}]
    }}
]


def table(db, title, sql):
    cursor = db.execute(sql)
    names = [item[0] for item in cursor.description]
    rows = cursor.fetchall()
    print(f"\n{title} ({len(rows)} rows)")
    print(" | ".join(names))
    for row in rows:
        print(" | ".join("-" if value is None else str(value) for value in row))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--mongo-uri", default=None)
    args = parser.parse_args()
    with sqlite3.connect(ROOT / "warehouse.db") as db:
        print(f"SQLite encounters: {db.execute('SELECT COUNT(*) FROM fact_encounter').fetchone()[0]}")
        print(f"SQLite foreign key issues: {len(db.execute('PRAGMA foreign_key_check').fetchall())}")
        table(db, "Derived service line comparison", SERVICE_LINE_SQL)
        table(db, "Condition comparison with LAG", CONDITION_SQL)
    if args.mongo_uri:
        try:
            from pymongo import MongoClient
        except ImportError as exc:
            raise SystemExit("MongoDB requested: install pymongo with pip install -r requirements.txt") from exc
        client = MongoClient(args.mongo_uri, serverSelectionTimeoutMS=3000)
        client.admin.command("ping")
        coll = client.group3_healthcare.encounter_context
        print("\nMongoDB $facet result (source-backed context, no clinical notes):")
        print(list(coll.aggregate(FACET)))
        client.close()
    else:
        print("\nMongoDB $facet: NOT EXECUTED (pass --mongo-uri with a running server)")


if __name__ == "__main__":
    main()
