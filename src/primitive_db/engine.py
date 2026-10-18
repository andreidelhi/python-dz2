"""Interactive loop and orchestration of database commands."""

import shlex

import prompt

from primitive_db import core
from primitive_db.constants import HELP_TEXT, META_FILE, PROMPT
from primitive_db.utils import (
    load_metadata,
    remove_table_data,
    save_metadata,
    save_table_data,
)


def print_help():
    """Print all currently supported commands."""
    print(HELP_TEXT)


def execute(command):
    """Parse and execute one command; return False only for exit."""
    args = shlex.split(command)
    if not args:
        return True
    operation = args[0].lower()
    metadata = load_metadata(META_FILE)
    if operation == "exit" and len(args) == 1:
        return False
    elif operation == "help" and len(args) == 1:
        print_help()
    elif operation == "create_table" and len(args) >= 3:
        table_name = args[1]
        result = core.create_table(metadata, table_name, args[2:])
        save_table_data(table_name, [])
        save_metadata(META_FILE, result)
        columns = ", ".join(result[table_name])
        print(f'Таблица "{table_name}" успешно создана со столбцами: {columns}')
    elif operation == "drop_table" and len(args) == 2:
        table_name = args[1]
        result = core.drop_table(metadata, table_name)
        remove_table_data(table_name)
        save_metadata(META_FILE, result)
        print(f'Таблица "{table_name}" успешно удалена.')
    elif operation == "list_tables" and len(args) == 1:
        if not metadata:
            print("Таблиц нет.")
        for table_name in sorted(metadata):
            print(f"- {table_name}")
    elif operation in {"exit", "help", "create_table", "drop_table", "list_tables"}:
        raise ValueError("Некорректное значение аргументов. Попробуйте снова.")
    else:
        print(f"Функции {args[0]} нет. Попробуйте снова.")
    return True


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
