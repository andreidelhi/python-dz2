"""Storage and end-to-end regressions against disposable databases."""

import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from primitive_db import core, engine
from primitive_db.decorators import create_cacher, handle_db_errors, log_time
from primitive_db.utils import load_metadata, load_table_data, save_table_data


@contextlib.contextmanager
def database():
    """Run a test in a fresh directory and capture console output."""
    with tempfile.TemporaryDirectory() as folder, contextlib.chdir(folder):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            yield Path(folder), output


def create_users():
    """Create the schema shared by CRUD scenarios."""
    engine.execute("create_table users name:str age:int is_active:bool")


def test_metadata_defaults_and_unicode_round_trip():
    with database():
        assert load_metadata("db_meta.json") == {}
        assert load_table_data("users") == []
        create_users()
        engine.execute('insert into users values ("Сергей", 28, true)')
        assert load_metadata("db_meta.json")["users"][0] == "ID:int"
        assert load_table_data("users") == [
            {"ID": 1, "name": "Сергей", "age": 28, "is_active": True}
        ]


def test_invalid_schema_does_not_change_metadata():
    with database():
        for columns in [
            ["age:float"],
            ["name:str", "name:int"],
            ["Age:int", "age:int"],
            ["ID:str"],
            ["id:int"],
            ["a:str:bool"],
            ["../name:str"],
        ]:
            metadata = {}
            assert core.create_table(metadata, "users", columns) is None
            assert metadata == {}


def test_explicit_id_is_not_duplicated():
    with database():
        metadata = core.create_table({}, "users", ["name:str", "ID:int"])
        assert metadata == {"users": ["ID:int", "name:str"]}


def test_bad_insert_does_not_write_data():
    with database():
        create_users()
        for values in ['("Anna", 28)', '("Anna", true, true)', '("Anna", 28, 1)']:
            engine.execute(f"insert into users values {values}")
        assert load_table_data("users") == []


def test_id_uses_maximum_instead_of_row_count():
    with database():
        create_users()
        save_table_data(
            "users",
            [
                {"ID": 2, "name": "A", "age": 1, "is_active": True},
                {"ID": 7, "name": "B", "age": 2, "is_active": False},
            ],
        )
        engine.execute('insert into users values ("C", 3, true)')
        assert [row["ID"] for row in load_table_data("users")] == [2, 7, 8]


def test_select_update_delete_and_drop():
    with database() as (folder, output):
        create_users()
        engine.execute('insert into users values ("Sergei", 28, true)')
        engine.execute('insert into users values ("Anna", 24, false)')
        engine.execute('select from users where name = "Sergei"')
        assert "Sergei" in output.getvalue()
        engine.execute('update users set age=29, is_active=false where name="Sergei"')
        assert load_table_data("users")[0]["age"] == 29
        engine.execute("info users")
        assert "Количество записей: 2" in output.getvalue()
        with patch("primitive_db.decorators.prompt.string", return_value="y"):
            engine.execute("delete from users where ID=1")
            assert [row["name"] for row in load_table_data("users")] == ["Anna"]
            engine.execute("drop_table users")
        assert load_metadata("db_meta.json") == {}
        assert not (folder / "data/users.json").exists()


def test_destructive_actions_require_exact_confirmation():
    with database():
        create_users()
        engine.execute('insert into users values ("Anna", 24, false)')
        for answer in ["n", "", "Y", "yes", " y"]:
            with patch("primitive_db.decorators.prompt.string", return_value=answer):
                engine.execute("delete from users where ID=1")
                engine.execute("drop_table users")
            assert "users" in load_metadata("db_meta.json")
            assert len(load_table_data("users")) == 1


def test_empty_table_and_no_matches():
    with database() as (_, output):
        create_users()
        engine.execute("select from users")
        engine.execute("update users set age=1 where ID=99")
        with patch("primitive_db.decorators.prompt.string", return_value="y"):
            engine.execute("delete from users where ID=99")
        assert output.getvalue().count("Записей не найдено.") == 3
        assert load_table_data("users") == []


def test_invalid_conditions_and_id_updates_preserve_data():
    with database():
        create_users()
        engine.execute('insert into users values ("Anna", 24, false)')
        original = load_table_data("users")
        invalid = [
            "update users set ID=2 where ID=1",
            'update users set age="25" where ID=1',
            "update users set missing=1 where ID=1",
            "update users set age=25 where ID=true",
            "delete from users where missing=1",
            "select from users where age=true",
        ]
        for command in invalid:
            engine.execute(command)
            assert load_table_data("users") == original


def test_direct_update_validates_both_where_and_set_types():
    with database():
        rows = [{"ID": 1, "age": 24}]
        assert core.update(rows, {"age": 25}, {"age": "24"}) is None
        assert rows == [{"ID": 1, "age": 24}]


def test_cache_refreshes_after_writes_and_does_not_leak_mutations():
    with database():
        rows = [{"ID": 1, "name": "A"}]
        result = core.select(rows)
        result[0]["name"] = "Changed outside"
        result.append({"ID": 2, "name": "Extra"})
        assert core.select(rows) == rows
        rows[0]["name"] = "B"
        assert core.select(rows)[0]["name"] == "B"
        assert core.select(rows, {"ID": True}) == []
        assert core.select(rows, {"ID": 1}) == rows


def test_cli_select_cache_after_insert_update_delete():
    with database() as (_, output):
        create_users()
        for command in [
            "select from users",
            'insert into users values ("Anna", 24, false)',
            "select from users",
            "update users set age=25 where ID=1",
            "select from users where age=25",
            "select from users where age=24",
        ]:
            engine.execute(command)
        with patch("primitive_db.decorators.prompt.string", return_value="y"):
            engine.execute("delete from users where ID=1")
        engine.execute("select from users")
        assert load_table_data("users") == []
        assert output.getvalue().count("Записей не найдено.") == 3


def test_closure_computes_once_for_identical_key():
    cache = create_cacher()
    calls = []

    def calculate():
        calls.append(True)
        return [42]

    assert cache("key", calculate) == [42]
    assert cache("key", calculate) == [42]
    assert len(calls) == 1
    assert cache("other", calculate) == [42]
    assert len(calls) == 2


def test_broken_json_is_reported_without_overwriting():
    with database() as (folder, output):
        create_users()
        target = folder / "data/users.json"
        target.write_text("{broken", encoding="utf-8")
        engine.execute('insert into users values ("Anna", 24, false)')
        assert target.read_text(encoding="utf-8") == "{broken"
        assert "Ошибка валидации" in output.getvalue()
        (folder / "db_meta.json").write_text("[]", encoding="utf-8")
        engine.execute("list_tables")
        assert "Неверный формат файла" in output.getvalue()


def test_corrupt_rows_and_duplicate_ids_are_rejected():
    with database():
        create_users()
        good = {"ID": 1, "name": "Anna", "age": 24, "is_active": False}
        for rows in [[good, good], [{**good, "ID": 0}], [{**good, "age": True}], [1]]:
            save_table_data("users", rows)
            engine.execute('insert into users values ("Bob", 20, true)')
            assert json.loads(Path("data/users.json").read_text()) == rows


def test_unsafe_names_never_create_files_outside_data():
    with database() as (folder, _):
        for name in ["../escape", "/tmp/escape", "bad/name", "", "two words"]:
            assert core.create_table({}, name, ["name:str"]) is None
        assert list(folder.iterdir()) == []


def test_error_decorator_handles_required_exceptions():
    with contextlib.redirect_stdout(io.StringIO()) as output:
        for error in [KeyError("missing"), ValueError("bad type"), FileNotFoundError()]:

            @handle_db_errors
            def fail():
                """Raise the exception supplied by the test."""
                raise error

            assert fail() is None
        assert output.getvalue().count("\n") == 3


def test_timer_keeps_result_and_formats_three_decimals():
    @log_time
    def action():
        """Return the value under test."""
        return 42

    with contextlib.redirect_stdout(io.StringIO()) as output:
        with patch("primitive_db.decorators.time.monotonic", side_effect=[1, 1.125]):
            assert action() == 42
    assert output.getvalue() == "Функция action выполнилась за 0.125 секунд.\n"


def test_real_cli_persists_between_processes_and_recovers_from_errors():
    with database() as (folder, _):
        executable = (
            shutil.which("database") or Path(sys.executable).parent / "database"
        )
        first = subprocess.run(
            [str(executable)],
            input="\nwrong\ncreate_table users name:str age:int "
            'is_active:bool\ninsert into users values ("Anna", 24, false)\nexit\n',
            text=True,
            capture_output=True,
            cwd=folder,
            timeout=10,
            check=True,
            env=dict(os.environ, PYTHONIOENCODING="utf-8"),
        )
        second = subprocess.run(
            [str(executable)],
            input="select from users\nexit\n",
            text=True,
            capture_output=True,
            cwd=folder,
            timeout=10,
            check=True,
        )
        assert "Попробуйте снова" in first.stdout
        assert "Anna" in second.stdout
        assert "Traceback" not in first.stderr + second.stderr


def test_cli_eof_exits_cleanly():
    with database() as (folder, _):
        executable = (
            shutil.which("database") or Path(sys.executable).parent / "database"
        )
        result = subprocess.run(
            [str(executable)],
            input="",
            text=True,
            capture_output=True,
            cwd=folder,
            timeout=10,
            check=True,
        )
        assert "До свидания!" in result.stdout


def load_tests(_loader, _tests, _pattern):
    """Expose ordinary test functions to unittest without defining classes."""
    return unittest.TestSuite(
        unittest.FunctionTestCase(func)
        for name, func in globals().items()
        if name.startswith("test_")
    )
