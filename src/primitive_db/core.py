"""Procedural database schema and row operations."""

from primitive_db.constants import FIRST_ID, ID_COLUMN, ID_DEFINITION, VALID_TYPES
from primitive_db.decorators import confirm_action, handle_db_errors, log_time
from primitive_db.utils import load_table_data, validate_name


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


@handle_db_errors
def create_table(metadata, table_name, columns):
    """Create a table schema with an automatic integer ID column."""
    validate_name(table_name)
    if table_name in metadata:
        raise ValueError(f'Таблица "{table_name}" уже существует.')
    parsed = _parse_columns(columns)
    metadata[table_name] = parsed
    return metadata


@handle_db_errors
@confirm_action("удаление таблицы")
def drop_table(metadata, table_name):
    """Remove an existing table from the metadata dictionary."""
    table_schema(metadata, table_name)
    del metadata[table_name]
    return metadata


def validate_fields(metadata, table_name, fields, allow_id=True):
    """Validate field names and exact Python types against the table schema."""
    schema = table_schema(metadata, table_name)
    for name, value in fields.items():
        if name not in schema:
            raise KeyError(f'Столбец "{name}" не найден.')
        if name == ID_COLUMN and not allow_id:
            raise ValueError("Изменять автоматически созданный ID нельзя")
        if type(value) is not VALID_TYPES[schema[name]]:
            raise ValueError(f'Столбец "{name}" ожидает тип {schema[name]}')


def validate_rows(metadata, table_name, rows):
    """Reject corrupt row shapes, invalid types and duplicate stored IDs."""
    schema = table_schema(metadata, table_name)
    seen_ids = set()
    for row in rows:
        if set(row) != set(schema):
            raise ValueError(f'Повреждены записи таблицы "{table_name}"')
        validate_fields(metadata, table_name, row)
        row_id = row[ID_COLUMN]
        if row_id < FIRST_ID or row_id in seen_ids:
            raise ValueError("ID должны быть положительными и уникальными")
        seen_ids.add(row_id)


@handle_db_errors
@log_time
def insert(metadata, table_name, values):
    """Append a validated row and return all rows with an automatic unique ID."""
    schema = table_schema(metadata, table_name)
    names = [name for name in schema if name != ID_COLUMN]
    if len(values) != len(names):
        raise ValueError(f"Ожидалось значений: {len(names)}, получено: {len(values)}")
    fields = dict(zip(names, values))
    validate_fields(metadata, table_name, fields)
    rows = load_table_data(table_name)
    validate_rows(metadata, table_name, rows)
    new_id = max((row[ID_COLUMN] for row in rows), default=FIRST_ID - 1) + 1
    rows.append({ID_COLUMN: new_id, **fields})
    return rows


def _matches(row, where_clause):
    """Compare field types as well as values, so True does not match integer 1."""
    return all(
        name in row and type(row[name]) is type(value) and row[name] == value
        for name, value in where_clause.items()
    )


@handle_db_errors
@log_time
def select(table_data, where_clause=None):
    """Return independent copies of rows matching all equality conditions."""
    return [
        row.copy()
        for row in table_data
        if where_clause is None or _matches(row, where_clause)
    ]


@handle_db_errors
def update(table_data, set_clause, where_clause):
    """Return rows with validated assignments applied to matching records."""
    if not set_clause or not where_clause:
        raise ValueError("Для update нужны непустые set и where")
    if ID_COLUMN in set_clause:
        raise ValueError("Изменять автоматически созданный ID нельзя")
    for row in table_data:
        for name, value in {**where_clause, **set_clause}.items():
            if name not in row:
                raise KeyError(f'Столбец "{name}" не найден.')
            if type(row[name]) is not type(value):
                raise ValueError(f'Неверный тип значения столбца "{name}"')
    return [
        {**row, **set_clause} if _matches(row, where_clause) else row.copy()
        for row in table_data
    ]


@handle_db_errors
@confirm_action("удаление записей")
def delete(table_data, where_clause):
    """Return all rows except those matching a nonempty WHERE condition."""
    if not where_clause:
        raise ValueError("Для delete нужно непустое where")
    return [row.copy() for row in table_data if not _matches(row, where_clause)]
