"""Procedural database schema and row operations."""

from primitive_db.constants import ID_COLUMN, ID_DEFINITION, VALID_TYPES
from primitive_db.utils import validate_name


def _parse_columns(columns):
    """Validate column declarations and place the generated ID first."""
    result = [ID_DEFINITION]
    seen = {ID_COLUMN.casefold()}
    explicit_id = False
    for column in columns:
        if not isinstance(column, str) or column.count(":") != 1:
            raise ValueError(f"Некорректное значение: {column}. Попробуйте снова.")
        name, type_name = column.split(":")
        validate_name(name)
        if type_name not in VALID_TYPES:
            raise ValueError(f"Неизвестный тип {type_name}; допустимы int, str, bool")
        if name.casefold() == ID_COLUMN.casefold():
            if name != ID_COLUMN or type_name != "int" or explicit_id:
                raise ValueError("Столбец ID должен быть единственным и иметь тип int")
            explicit_id = True
            continue
        if name.casefold() in seen:
            raise ValueError(f"Столбец {name} указан повторно")
        seen.add(name.casefold())
        result.append(column)
    return result


def table_schema(metadata, table_name):
    """Return a validated column-name/type mapping for an existing table."""
    validate_name(table_name)
    if table_name not in metadata:
        raise KeyError(f'Таблица "{table_name}" не существует.')
    columns = metadata[table_name]
    if not isinstance(columns, list) or _parse_columns(columns) != columns:
        raise ValueError(f'Повреждена схема таблицы "{table_name}"')
    return dict(column.split(":") for column in columns)


def create_table(metadata, table_name, columns):
    """Create a table schema with an automatic integer ID column."""
    validate_name(table_name)
    if table_name in metadata:
        raise ValueError(f'Таблица "{table_name}" уже существует.')
    parsed = _parse_columns(columns)
    metadata[table_name] = parsed
    return metadata


def drop_table(metadata, table_name):
    """Remove an existing table from the metadata dictionary."""
    table_schema(metadata, table_name)
    del metadata[table_name]
    return metadata
