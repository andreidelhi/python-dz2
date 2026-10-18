"""Load, validate and save database JSON files."""

import json
import os

from primitive_db.constants import DATA_DIR, ENCODING, JSON_INDENT


def validate_name(name):
    """Reject empty names and paths; allow ordinary Python-style identifiers."""
    if not isinstance(name, str) or not name.isidentifier():
        raise ValueError(f"Некорректное имя: {name}")
    return name


def _load_json(filepath, default, expected_type):
    """Read JSON, handling a missing file without concealing corrupt data."""
    try:
        with open(filepath, encoding=ENCODING) as stream:
            value = json.load(stream)
    except FileNotFoundError:
        return default
    if not isinstance(value, expected_type):
        raise ValueError(f"Неверный формат файла {filepath}")
    return value


def _save_json(filepath, data):
    """Replace the JSON file atomically after writing all data."""
    directory = os.path.dirname(os.fspath(filepath))
    if directory:
        os.makedirs(directory, exist_ok=True)
    temporary = f"{filepath}.tmp"
    try:
        with open(temporary, "w", encoding=ENCODING) as stream:
            json.dump(data, stream, ensure_ascii=False, indent=JSON_INDENT)
            stream.write("\n")
        os.replace(temporary, filepath)
    finally:
        if os.path.exists(temporary):
            os.remove(temporary)


def load_metadata(filepath):
    """Return table schemas, or an empty dictionary for a missing file."""
    return _load_json(filepath, {}, dict)


def save_metadata(filepath, data):
    """Save the dictionary containing table schemas."""
    _save_json(filepath, data)


def table_path(table_name):
    """Return a safe path within the data directory."""
    validate_name(table_name)
    return os.path.join(DATA_DIR, f"{table_name}.json")


def load_table_data(table_name):
    """Return stored rows, or an empty list for a missing table file."""
    rows = _load_json(table_path(table_name), [], list)
    if not all(isinstance(row, dict) for row in rows):
        raise ValueError(f"Неверный формат записей таблицы {table_name}")
    return rows


def save_table_data(table_name, data):
    """Persist the rows of a table."""
    _save_json(table_path(table_name), data)


def remove_table_data(table_name):
    """Remove a dropped table's file, if one exists."""
    try:
        os.remove(table_path(table_name))
    except FileNotFoundError:
        pass
