"""Prepare an xdev data directory from a labeled CSV file.

The input format is the exported labeled dataset CSV used by the local
``phe/datasets/labeled_dataset`` directory. Rows must contain ``met_uuid`` and
``met_link``. Label fields are read from columns prefixed with ``原文_`` and are
normalized to Phoenix workspace field names by stripping the prefix.
"""

from __future__ import annotations

import argparse
import csv
import json
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[1]

FIELD_ALIASES = {
    "股东大会届次次数": "股东大会届次",
}


def normalize_field_name(column: str) -> str | None:
    if not column.startswith("原文_"):
        return None
    field = column.removeprefix("原文_")
    return FIELD_ALIASES.get(field, field)


def read_rows(csv_file: Path, *, limit: int) -> tuple[list[dict[str, str]], list[str]]:
    rows: list[dict[str, str]] = []
    with csv_file.open(newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        if not reader.fieldnames:
            raise SystemExit(f"CSV has no header: {csv_file}")
        label_fields = [
            field
            for field in (normalize_field_name(column) for column in reader.fieldnames)
            if field
        ]
        for row in reader:
            if row.get("met_uuid") and row.get("met_link"):
                rows.append(row)
            if len(rows) >= limit:
                break
    if not rows:
        raise SystemExit(f"No usable rows found in {csv_file}")
    return rows, label_fields


def download_pdfs(rows: list[dict[str, str]], pdf_dir: Path) -> None:
    pdf_dir.mkdir(parents=True, exist_ok=True)
    for index, row in enumerate(rows, start=1):
        doc_id = row["met_uuid"].strip()
        url = row["met_link"].strip()
        target = pdf_dir / f"{doc_id}.pdf"
        if target.exists() and target.stat().st_size > 0:
            print(f"[{index}/{len(rows)}] exists: {doc_id}")
            continue
        print(f"[{index}/{len(rows)}] download: {doc_id} <- {url}")
        urllib.request.urlretrieve(url, target)
        if target.stat().st_size <= 0:
            raise SystemExit(f"Downloaded empty PDF: {target}")


def write_labels(rows: list[dict[str, str]], label_fields: list[str], data_dir: Path) -> None:
    labels_dir = data_dir / "labels"
    labels_dir.mkdir(parents=True, exist_ok=True)
    for row in rows:
        label: dict[str, str] = {}
        for column, value in row.items():
            field = normalize_field_name(column)
            if field:
                label[field] = value or ""
        for field in label_fields:
            label.setdefault(field, "")
        (labels_dir / f"{row['met_uuid'].strip()}.json").write_text(
            json.dumps(label, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )


def write_schema(label_fields: list[str], data_dir: Path) -> None:
    schema = {
        "type": "object",
        "data": {field: "str" for field in label_fields},
    }
    (data_dir / "schema.json").write_text(
        json.dumps(schema, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def run_xdev_import(pdf_dir: Path, data_dir: Path) -> None:
    data_dir.mkdir(parents=True, exist_ok=True)
    command = [
        "uv",
        "run",
        "xdev",
        "import-data",
        "--pdfs",
        str(pdf_dir),
        "--data-dir",
        str(data_dir),
    ]
    subprocess.run(command, cwd=str(REPO_ROOT), check=True)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepare xdev data from labeled CSV.")
    parser.add_argument("--csv-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True, help="Output .xdev directory.")
    parser.add_argument("--pdf-dir", type=Path, help="Directory for downloaded PDFs.")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--overwrite", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    output_dir = args.output_dir.resolve()
    pdf_dir = (args.pdf_dir or output_dir.parent / "pdfs").resolve()
    if args.overwrite:
        shutil.rmtree(output_dir, ignore_errors=True)
        shutil.rmtree(pdf_dir, ignore_errors=True)
    if output_dir.exists() and any(output_dir.iterdir()):
        raise SystemExit(f"Output dir already exists and is not empty: {output_dir}")

    rows, label_fields = read_rows(args.csv_file.resolve(), limit=args.limit)
    download_pdfs(rows, pdf_dir)
    run_xdev_import(pdf_dir, output_dir)
    write_labels(rows, label_fields, output_dir)
    write_schema(label_fields, output_dir)
    print(f"Prepared xdev data: {output_dir}")
    print(f"Documents: {len(rows)}")
    print(f"Fields: {len(label_fields)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
