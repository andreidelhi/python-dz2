"""Database paths, supported types and console messages."""

META_FILE = "db_meta.json"
DATA_DIR = "data"
VALID_TYPES = {"int": int, "str": str, "bool": bool}
ID_COLUMN = "ID"
ID_DEFINITION = "ID:int"
FIRST_ID = 1
ENCODING = "utf-8"
JSON_INDENT = 2
CACHE_LIMIT = 128
PROMPT = "Введите команду: "
HELP_TEXT = """***Процесс работы с таблицей***
Функции:
<command> create_table <имя> <столбец:тип> ... - создать таблицу
<command> list_tables - показать список всех таблиц
<command> drop_table <имя> - удалить таблицу
<command> insert into <имя> values (...) - добавить запись без ID
<command> select from <имя> [where <столбец> = <значение>] - прочитать записи
<command> help - справочная информация
<command> exit - выйти из программы"""
