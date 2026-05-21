import pandas as pd

def parse_inventory_summary(path: str):
    df = pd.read_excel(path)
    df = df[[
        "Category", "Name", "Description",
        "On Hand", "Available", "On SO", "On PO"
    ]].dropna(subset=["Name", "Description"])
    return df.to_dict(orient="records")

def parse_physical_count(path: str):
    df = pd.read_excel(path)

    required_columns = ["Name", "Actual Count", "count_date", "responsable"]
    for col in required_columns:
        if col not in df.columns:
            raise ValueError(f"Columna faltante: {col}")

    return df.to_dict(orient="records")
