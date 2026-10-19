"""Extended tests for data integrity, grammar, cache and CLI recovery."""

import contextlib
import importlib
import io
import json
import os
import random
import runpy
import shutil
import signal
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from primitive_db import core, engine, parser, utils
from primitive_db.constants import CACHE_LIMIT
from primitive_db.decorators import confirm_action, create_cacher


@contextlib.contextmanager
def database():
    """Capture output and isolate all filesystem changes from the real database."""
    with tempfile.TemporaryDirectory() as folder, contextlib.chdir(folder):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            yield Path(folder), output


def execute(command):
    """Run a command and return only its output."""
    with contextlib.redirect_stdout(io.StringIO()) as output:
        result = engine.execute(command)
    return result, output.getvalue()


def create_users():
    """Create a table and one initial row."""
    engine.execute("create_table users name:str age:int is_active:bool")
    engine.execute('insert into users values ("Sergei", 28, true)')


def test_create_preserves_unregistered_data_file():
    with database():
        original = [{"ID": 1, "name": "Unregistered data"}]
        utils.save_table_data("users", original)
        result, text = execute("create_table users name:str")
        assert result is not False and "Ошибка" in text
        assert utils.load_table_data("users") == original
        assert utils.load_metadata("db_meta.json") == {}


def test_create_does_not_overwrite_alias_on_case_insensitive_filesystem():
    with database() as (folder, _):
        create_users()
        original = utils.load_table_data("users")
        lower = folder / "data/users.json"
        upper = folder / "data/Users.json"
        if upper.exists() and os.path.samefile(lower, upper):
            result, text = execute("create_table Users name:str")
            assert result is not False and "Ошибка" in text
            assert utils.load_table_data("users") == original


def test_create_rolls_back_new_data_file_if_metadata_save_fails():
    with database() as (folder, _):
        original_replace = utils.os.replace

        def fail_metadata(source, target):
            """Simulate a write error for metadata only."""
            if str(target) == "db_meta.json":
                raise PermissionError("metadata is read-only")
            return original_replace(source, target)

        with patch("primitive_db.utils.os.replace", side_effect=fail_metadata):
            result, text = execute("create_table users name:str")
        assert result is not False and "Ошибка работы с файлами" in text
        assert utils.load_metadata("db_meta.json") == {}
        assert not (folder / "data/users.json").exists()
        assert not list(folder.rglob("*.tmp"))


def test_drop_preserves_rows_if_metadata_save_fails():
    with database():
        create_users()
        original_rows = utils.load_table_data("users")
        original_metadata = utils.load_metadata("db_meta.json")
        with patch(
            "primitive_db.utils.os.replace", side_effect=PermissionError("denied")
        ):
            with patch("primitive_db.decorators.prompt.string", return_value="y"):
                result, text = execute("drop_table users")
        assert result is not False and "Ошибка работы с файлами" in text
        assert utils.load_metadata("db_meta.json") == original_metadata
        assert utils.load_table_data("users") == original_rows


def test_drop_restores_metadata_if_data_removal_fails():
    with database():
        create_users()
        original_rows = utils.load_table_data("users")
        original_metadata = utils.load_metadata("db_meta.json")
        with patch("primitive_db.utils.os.remove", side_effect=PermissionError()):
            with patch("primitive_db.decorators.prompt.string", return_value="y"):
                result, text = execute("drop_table users")
        assert result is not False and "Ошибка работы с файлами" in text
        assert utils.load_metadata("db_meta.json") == original_metadata
        assert utils.load_table_data("users") == original_rows


def test_atomic_row_write_failure_preserves_old_file():
    with database() as (folder, _):
        create_users()
        original = (folder / "data/users.json").read_bytes()
        with patch("primitive_db.utils.os.replace", side_effect=PermissionError()):
            result, text = execute('insert into users values ("Anna", 24, false)')
        assert result is not False and "Ошибка работы с файлами" in text
        assert (folder / "data/users.json").read_bytes() == original
        assert not list(folder.rglob("*.tmp"))


def test_missing_metadata_and_table_errors_are_recoverable():
    with database():
        for command in [
            "info missing",
            "select from missing",
            "update missing set age=1 where ID=1",
            'insert into missing values ("x")',
            "delete from missing where ID=1",
        ]:
            result, text = execute(command)
            assert result is not False and "не существует" in text, command
        with patch("primitive_db.decorators.prompt.string", return_value="y"):
            result, text = execute("drop_table missing")
        assert result is not False and "не существует" in text
        create_users()
        assert len(utils.load_table_data("users")) == 1


def test_duplicate_table_creation_preserves_schema_and_rows():
    with database():
        create_users()
        original = utils.load_table_data("users")
        _, text = execute("create_table users different:bool")
        assert "уже существует" in text
        assert utils.load_table_data("users") == original
        assert utils.load_metadata("db_meta.json")["users"] == [
            "ID:int",
            "name:str",
            "age:int",
            "is_active:bool",
        ]


def test_all_field_types_are_required_and_exact():
    with database():
        create_users()
        original = utils.load_table_data("users")
        invalid = [
            [],
            ["A"],
            ["A", 1],
            ["A", 1, True, 2],
            [1, 2, True],
            [False, 2, True],
            ["A", True, True],
            ["A", "2", True],
            ["A", 2.0, True],
            ["A", None, True],
            ["A", 2, 1],
            ["A", 2, "true"],
            ["A", 2, None],
        ]
        metadata = utils.load_metadata("db_meta.json")
        for values in invalid:
            assert core.insert(metadata, "users", values) is None, values
            assert utils.load_table_data("users") == original


def test_id_only_schema_and_recreation():
    with database():
        engine.execute("create_table counters ID:int")
        engine.execute("insert into counters values ()")
        engine.execute("insert into counters values ()")
        assert utils.load_table_data("counters") == [{"ID": 1}, {"ID": 2}]
        with patch("primitive_db.decorators.prompt.string", return_value="y"):
            engine.execute("drop_table counters")
        engine.execute("create_table counters value:str")
        engine.execute('insert into counters values ("New")')
        assert utils.load_table_data("counters") == [{"ID": 1, "value": "New"}]


def test_multiple_tables_do_not_share_state():
    with database():
        create_users()
        engine.execute("create_table products title:str price:int available:bool")
        engine.execute('insert into products values ("Tea", 100, true)')
        engine.execute('update products set price=120 where title="Tea"')
        assert utils.load_table_data("users")[0]["age"] == 28
        assert utils.load_table_data("products")[0]["price"] == 120
        with patch("primitive_db.decorators.prompt.string", return_value="y"):
            engine.execute("drop_table products")
        assert len(utils.load_table_data("users")) == 1
        assert list(utils.load_metadata("db_meta.json")) == ["users"]


def test_keywords_as_column_names_and_multiple_set_clauses():
    with database():
        engine.execute("create_table words where:str set:str and:str from:str")
        engine.execute('insert into words values ("a", "b", "c", "d")')
        result, text = execute(
            'update words set where="where", set="set", and="and", from="from" '
            'where where="a" and and="c"'
        )
        assert result is True, text
        assert utils.load_table_data("words") == [
            {"ID": 1, "where": "where", "set": "set", "and": "and", "from": "from"}
        ]


def test_updates_and_deletes_affect_all_matching_rows():
    with database():
        create_users()
        for name in ["Anna", "Bob", "Carol"]:
            engine.execute(f'insert into users values ("{name}", 28, true)')
        engine.execute("update users set age=29 where age=28 and is_active=true")
        assert [row["age"] for row in utils.load_table_data("users")] == [29] * 4
        with patch("primitive_db.decorators.prompt.string", return_value="y"):
            engine.execute("delete from users where age=29")
        assert utils.load_table_data("users") == []


def test_corrupt_metadata_shapes_never_crash_or_overwrite_files():
    with database() as (folder, _):
        for value in [
            None,
            [],
            "text",
            7,
            {"users": None},
            {"users": "name:str"},
            {"users": ["name:str"]},
            {"users": ["ID:int", None]},
            {"users": ["ID:int", "age:float"]},
            {"users": ["ID:int", "age:int", "Age:str"]},
        ]:
            target = folder / "db_meta.json"
            original = json.dumps(value)
            target.write_text(original)
            for command in ["select from users", "info users"]:
                result, text = execute(command)
                assert result is not False and "Ошибка" in text, value
                assert target.read_text() == original


def test_corrupt_row_columns_and_ids_are_rejected():
    with database():
        create_users()
        good = utils.load_table_data("users")[0]
        invalid = [
            {key: value for key, value in good.items() if key != "age"},
            {**good, "extra": "field"},
            {**good, "ID": True},
            {**good, "ID": -1},
            {**good, "ID": "1"},
        ]
        for row in invalid:
            utils.save_table_data("users", [row])
            result, text = execute("select from users")
            assert result is not False and "Ошибка" in text
            assert utils.load_table_data("users") == [row]


def test_direct_update_and_delete_reject_dangerous_arguments():
    with database():
        rows = [{"ID": 1, "age": 28}]
        for updates, condition in [
            ({}, {"ID": 1}),
            ({"age": 29}, {}),
            ({"ID": 2}, {"ID": 1}),
            ({"missing": 1}, {"ID": 1}),
        ]:
            assert core.update(rows, updates, condition) is None
        with patch("primitive_db.decorators.prompt.string", return_value="y"):
            assert core.delete(rows, {}) is None
        assert rows == [{"ID": 1, "age": 28}]


def test_drop_tolerates_missing_data_file():
    with database() as (folder, _):
        create_users()
        (folder / "data/users.json").unlink()
        with patch("primitive_db.decorators.prompt.string", return_value="y"):
            result, text = execute("drop_table users")
        assert result is True and "успешно удалена" in text
        assert utils.load_metadata("db_meta.json") == {}


def test_invalid_utf8_and_empty_json_files_are_reported():
    with database() as (folder, _):
        create_users()
        target = folder / "data/users.json"
        for data in [b"", b"\xff\xfe", b"null", b"{}", b"[null]", b"[1]"]:
            target.write_bytes(data)
            result, text = execute("select from users")
            assert result is not False and "Ошибка" in text, data
            assert target.read_bytes() == data


def test_external_file_changes_are_loaded_on_every_command():
    with database():
        create_users()
        execute("select from users where age=28")
        utils.save_table_data(
            "users", [{"ID": 9, "name": "External", "age": 42, "is_active": False}]
        )
        _, text = execute("select from users where age=42")
        assert "External" in text and "Sergei" not in text
        utils.save_metadata("db_meta.json", {})
        result, text = execute("info users")
        assert result is not False and "не существует" in text


def test_confirm_action_does_not_invoke_cancelled_function():
    calls = []

    @confirm_action("тест")
    def action(value):
        """Record only confirmed calls."""
        calls.append(value)
        return value

    with contextlib.redirect_stdout(io.StringIO()):
        for answer in ["", "n", "Y", "yes", " y", "y ", None]:
            with patch("primitive_db.decorators.prompt.string", return_value=answer):
                assert action(42) is None
        assert calls == []
        with patch("primitive_db.decorators.prompt.string", return_value="y"):
            assert action(42) == 42
    assert calls == [42]


def test_cache_eviction_and_failed_computation():
    cache = create_cacher()
    calls = []
    for number in range(CACHE_LIMIT + 1):
        assert cache(number, lambda n=number: n) == number
    assert cache(0, lambda: calls.append(0) or "new") == "new"
    assert calls == [0]

    def fail():
        """Reject one cache computation."""
        raise ValueError("not cached")

    try:
        cache("error", fail)
    except ValueError:
        pass
    else:
        raise AssertionError("The value factory's error must propagate")
    assert cache("error", lambda: "retry") == "retry"


def test_select_reuses_cache_and_distinguishes_bool_and_integer_keys():
    with database():
        rows = [{"ID": 1, "value": "A"}, {"ID": 2, "value": "B"}]
        with patch("primitive_db.core._select_cache", new=create_cacher()):
            with patch("primitive_db.core._matches", wraps=core._matches) as matching:
                assert core.select(rows, {"ID": 1}) == [rows[0]]
                assert matching.call_count == 2
                assert core.select(rows, {"ID": 1}) == [rows[0]]
                assert matching.call_count == 2
                assert core.select(rows, {"ID": True}) == []
                assert matching.call_count == 4


def test_json_string_round_trips_for_one_thousand_literals():
    randomizer = random.Random(1729)
    alphabet = "abc XYZ0123,()=\\\"'\n\t\r#_яЁ中😀"
    for _ in range(1000):
        original = "".join(randomizer.choices(alphabet, k=randomizer.randrange(80)))
        literal = json.dumps(original, ensure_ascii=False)
        assert parser.parse_values(f"({literal})") == [original]
        assert parser.parse_where(f"name = {literal}") == {"name": original}
        assert parser.parse_set(f"name = {literal}") == {"name": original}


def test_malformed_commands_are_rejected_and_preserve_records():
    with database():
        create_users()
        original = utils.load_table_data("users")
        invalid = [
            "select",
            "select from",
            "select users",
            "select from users trailing",
            "select from users where age==28",
            "select from users where age!=28",
            "select from users where age > 28",
            "select from users where age=28 and",
            "select from users where age=(28)",
            "select from users where ID=true",
            "update users set age=29 where",
            "update users set where ID=1",
            "update users set age=29, where ID=1",
            "update users set age=29 age=30",
            "update users set age=29, age=30 where ID=1",
            "delete users where ID=1",
            "delete from users where ID=1 or ID=2",
            "insert into users values",
            "insert into users values ()",
            'insert into users values ("x", 1, null)',
            'insert into users values ("x", 1, 1)',
            'insert into users values ("x", 1, true, false)',
            'insert into users values ("x", 1, true);',
            "create_table users bad:unknown",
            "help extra",
            "exit extra",
            "drop_table ../users",
            "info /tmp/users",
        ]
        with patch("primitive_db.decorators.prompt.string", return_value="y"):
            for command in invalid:
                result, text = execute(command)
                assert result is not False and "Ошибка" in text, (command, text)
                assert utils.load_table_data("users") == original, command


def test_parser_rejects_incomplete_escapes_and_assignments():
    for text in ['("trailing' + "\\", "('trailing" + "\\"]:
        try:
            parser.parse_values(text)
        except ValueError:
            pass
        else:
            raise AssertionError("Unfinished escape accepted")
    for text in ["age=1 and", "age=1 or name=2", ""]:
        try:
            parser.parse_where(text)
        except ValueError:
            pass
        else:
            raise AssertionError(f"Invalid WHERE accepted: {text}")


def test_module_entry_point_and_interactive_loop():
    with database() as (_, output):
        commands = ["", "help", "list_tables", "unknown", "exit"]
        with patch("primitive_db.engine.prompt.string", side_effect=commands):
            runpy.run_module("primitive_db.main", run_name="__main__")
        text = output.getvalue()
        assert "***Примитивная база данных***" in text
        assert "Функции unknown нет. Попробуйте снова." in text
        assert "Таблиц нет." in text and "До свидания!" in text


def test_importing_main_does_not_start_interactive_input():
    with contextlib.redirect_stdout(io.StringIO()) as output:
        with patch("primitive_db.engine.run") as running:
            importlib.import_module("primitive_db.main")
            running.assert_not_called()
    assert output.getvalue() == ""


def test_loop_handles_eof_and_keyboard_interrupt():
    with database() as (_, output):
        for error in [EOFError(), KeyboardInterrupt()]:
            with patch("primitive_db.engine.prompt.string", side_effect=error):
                engine.run()
        assert output.getvalue().count("До свидания!") == 2


def test_random_crud_against_independent_reference_model():
    names = ["Анна", "O'Brien", "where", "", "x,y(z)=q", 'A "quote"', "😀"]
    for seed in range(25):
        rng = random.Random(seed)
        with database():
            engine.execute("create_table users name:str age:int is_active:bool")
            model = []
            with patch("primitive_db.decorators.prompt.string", return_value="y"):
                for _ in range(200):
                    operation = rng.choice(
                        ["insert", "insert", "update", "delete", "select"]
                    )
                    if operation == "insert":
                        name, age, active = (
                            rng.choice(names),
                            rng.randrange(-5, 100),
                            bool(rng.randrange(2)),
                        )
                        literal = json.dumps(name, ensure_ascii=False)
                        command = (
                            f"insert into users values "
                            f"({literal}, {age}, {str(active).lower()})"
                        )
                        new_id = max([row["ID"] for row in model], default=0) + 1
                        model.append(
                            dict(ID=new_id, name=name, age=age, is_active=active)
                        )
                    else:
                        target = (
                            rng.choice(model)["age"] if model else rng.randrange(100)
                        )
                        if operation == "update":
                            new_age = rng.randrange(-5, 100)
                            command = (
                                f"update users set age={new_age} where age={target}"
                            )
                            for row in model:
                                if row["age"] == target:
                                    row["age"] = new_age
                        elif operation == "delete":
                            command = f"delete from users where age={target}"
                            model = [row for row in model if row["age"] != target]
                        else:
                            command = f"select from users where age={target}"
                    result, text = execute(command)
                    assert result is True and "Ошибка" not in text, (
                        seed,
                        command,
                        text,
                    )
                    assert utils.load_table_data("users") == model, (seed, command)
                    expected = [row for row in model if row["is_active"]]
                    assert (
                        core.select(utils.load_table_data("users"), {"is_active": True})
                        == expected
                    )


def test_real_cli_confirmation_eof_keeps_data_and_returns_success():
    with database() as (folder, _):
        create_users()
        executable = (
            shutil.which("database") or Path(sys.executable).parent / "database"
        )
        for command in ["delete from users where ID=1", "drop_table users"]:
            result = subprocess.run(
                [str(executable)],
                input=command + "\n",
                text=True,
                capture_output=True,
                cwd=folder,
                timeout=10,
                check=True,
            )
            assert "До свидания!" in result.stdout
            assert "Traceback" not in result.stderr
            assert len(utils.load_table_data("users")) == 1


def test_real_cli_keyboard_interrupt_exits_cleanly():
    with database() as (folder, _):
        executable = (
            shutil.which("database") or Path(sys.executable).parent / "database"
        )
        process = subprocess.Popen(
            [str(executable)],
            cwd=folder,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
        )
        try:
            output = []
            while True:
                char = process.stdout.read(1)
                assert char, "CLI exited before displaying its prompt"
                output.append(char)
                if "".join(output).endswith("Введите команду: "):
                    break
            process.send_signal(signal.SIGINT)
            stdout, stderr = process.communicate(timeout=10)
            assert process.returncode == 0, stderr
            assert "До свидания!" in stdout
            assert "Traceback" not in stderr
        finally:
            if process.poll() is None:
                process.kill()
                process.communicate()


def load_tests(_loader, _tests, _pattern):
    """Expose function tests to the standard unittest runner."""
    return unittest.TestSuite(
        unittest.FunctionTestCase(func)
        for name, func in globals().items()
        if name.startswith("test_")
    )
