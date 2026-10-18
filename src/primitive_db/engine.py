"""Interactive loop and orchestration of database commands."""

import prompt
from prettytable import PrettyTable

from primitive_db import core
from primitive_db.constants import HELP_TEXT, META_FILE, PROMPT
from primitive_db.parser import parse_command
from primitive_db.utils import (
    load_metadata,
    load_table_data,
    remove_table_data,
    save_metadata,
    save_table_data,
)


def print_help():
    """Print all currently supported commands."""
    print(HELP_TEXT)


def execute(command):
    """Parse and execute one command; return False only for exit."""
    parsed = parse_command(command)
    operation = parsed["operation"]
    if operation == "empty":
        return True
    if operation == "exit":
        return False
    if operation == "help":
        print_help()
        return True
    metadata = load_metadata(META_FILE)
    if operation == "list_tables":
        if not metadata:
            print("Таблиц нет.")
        for table_name in sorted(metadata):
            print(f"- {table_name}")
        return True
    table_name = parsed["table"]
    if operation == "create_table":
        result = core.create_table(metadata, table_name, parsed["columns"])
        if result is not None:
            save_table_data(table_name, [])
            save_metadata(META_FILE, result)
            columns = ", ".join(result[table_name])
            print(f'Таблица "{table_name}" успешно создана со столбцами: {columns}')
    elif operation == "drop_table":
        result = core.drop_table(metadata, table_name)
        if result is not None:
            remove_table_data(table_name)
            save_metadata(META_FILE, result)
            print(f'Таблица "{table_name}" успешно удалена.')
    elif operation == "insert":
        result = core.insert(metadata, table_name, parsed["values"])
        if result is not None:
            save_table_data(table_name, result)
            row_id = result[-1]["ID"]
            print(f'Запись с ID={row_id} успешно добавлена в таблицу "{table_name}".')
    elif operation == "select":
        schema, rows = _read_rows(metadata, table_name)
        core.validate_fields(metadata, table_name, parsed["where"] or {})
        result = core.select(rows, parsed["where"])
        if result is not None:
            _print_rows(schema, result)
    elif operation == "update":
        _schema, rows = _read_rows(metadata, table_name)
        core.validate_fields(metadata, table_name, parsed["where"])
        core.validate_fields(metadata, table_name, parsed["set"], allow_id=False)
        matched = core.select(rows, parsed["where"])
        result = core.update(rows, parsed["set"], parsed["where"])
        if result is not None:
            save_table_data(table_name, result)
            if not matched:
                print("Записей не найдено.")
            for row in matched:
                row_id = row["ID"]
                print(
                    f'Запись с ID={row_id} в таблице "{table_name}" успешно обновлена.'
                )
    elif operation == "delete":
        _schema, rows = _read_rows(metadata, table_name)
        core.validate_fields(metadata, table_name, parsed["where"])
        matched = core.select(rows, parsed["where"])
        result = core.delete(rows, parsed["where"])
        if result is not None:
            save_table_data(table_name, result)
            if not matched:
                print("Записей не найдено.")
            for row in matched:
                row_id = row["ID"]
                print(
                    f'Запись с ID={row_id} успешно удалена из таблицы "{table_name}".'
                )
    return True


def _read_rows(metadata, table_name):
    """Load and validate an existing table before running a row command."""
    schema = core.table_schema(metadata, table_name)
    rows = load_table_data(table_name)
    core.validate_rows(metadata, table_name, rows)
    return schema, rows


def _print_rows(schema, rows):
    """Render SELECT results in column order, including an empty table header."""
    table = PrettyTable()
    table.field_names = list(schema)
    for row in rows:
        table.add_row([row[name] for name in schema])
    print(table)
    if not rows:
        print("Записей не найдено.")


def welcome():
    """Print the database welcome message and help."""
    print("***Примитивная база данных***")
    print_help()


def run():
    """Run the command loop and recover from malformed user input."""
    welcome()
    while True:
        try:
            command = prompt.string(PROMPT, empty=True)
            if command and execute(command) is False:
                break
        except (EOFError, KeyboardInterrupt):
            print()
            break
        except (KeyError, ValueError, OSError) as error:
            message = error.args[0] if error.args else str(error)
            print(f"Ошибка: {message}")
    print("До свидания!")
