from pathlib import Path
from config import Config
from utils.course_catalog import load_catalog, _load_xlsx_catalog, _load_csv_catalog  # temporary

if __name__ == "__main__":
    p = Path(Config.CATALOG_DIR)
    print("CATALOG_DIR:", p.resolve())
    print("XLSX files:", [x.name for x in p.glob("*.xlsx")])
    print("CSV files:", [x.name for x in p.glob("*.csv")])

    # Try XLSX alone (so we know if it works)
    xlsx_files = list(p.glob("*.xlsx"))
    if xlsx_files:
        items = _load_xlsx_catalog(xlsx_files[0])
        print("First XLSX rows loaded:", len(items))
        if items:
            print("Sample XLSX row:", items[0])

    # Full catalog (XLSX + CSV)
    catalog = load_catalog(Config.CATALOG_DIR)
    print("Catalog count:", len(catalog))
    with_prereq = [c for c in catalog if getattr(c, "prereq_text", None)]
    print("Rows with prereq_text:", len(with_prereq))
