"""Ingest and cleanse hospital patient records for downstream analysis."""

from pathlib import Path

import pandas as pd


INPUT_FILE = Path("hospital data analysis.csv")
OUTPUT_FILE = Path("cleaned_hospital_data.csv")
IDENTIFIER_COLUMNS = ("Admission_ID", "Patient_ID")


def find_identifier_column(dataframe: pd.DataFrame) -> str:
	"""Return the supported admission identifier column available in the data."""
	for column_name in IDENTIFIER_COLUMNS:
		if column_name in dataframe.columns:
			return column_name
	expected_columns = " or ".join(IDENTIFIER_COLUMNS)
	raise ValueError(f"The input file must contain {expected_columns}.")


def cleanse_hospital_data(input_file: Path) -> tuple[pd.DataFrame, dict[str, int]]:
	"""Load patient records and remove rows with invalid IDs or billing costs."""
	dataframe = pd.read_csv(input_file)
	identifier_column = find_identifier_column(dataframe)

	if "Cost" not in dataframe.columns:
		raise ValueError("The input file must contain a Cost column.")

	initial_row_count = len(dataframe)
	dataframe[identifier_column] = dataframe[identifier_column].replace(r"^\s*$", pd.NA, regex=True)
	dataframe = dataframe.dropna(subset=[identifier_column]).copy()
	missing_id_count = initial_row_count - len(dataframe)

	cleaned_cost = (
		dataframe["Cost"]
		.astype("string")
		.str.replace(r"[$,]", "", regex=True)
		.str.strip()
	)
	dataframe["Cost"] = pd.to_numeric(cleaned_cost, errors="coerce")
	invalid_cost_mask = dataframe["Cost"].isna() | dataframe["Cost"].lt(0)
	corrupted_cost_count = int(invalid_cost_mask.sum())
	dataframe = dataframe.loc[~invalid_cost_mask].copy()

	report = {
		"input_rows": initial_row_count,
		"removed_missing_ids": missing_id_count,
		"removed_corrupted_costs": corrupted_cost_count,
		"clean_rows": len(dataframe),
	}
	return dataframe, report


def main() -> None:
	cleaned_data, report = cleanse_hospital_data(INPUT_FILE)
	cleaned_data.to_csv(OUTPUT_FILE, index=False)

	print(f"Cleaned data saved to: {OUTPUT_FILE.resolve()}")
	for measure, value in report.items():
		print(f"{measure.replace('_', ' ').title()}: {value}")


if __name__ == "__main__":
	main()
