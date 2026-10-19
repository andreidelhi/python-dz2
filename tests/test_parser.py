"""Regression tests for CLI grammar and preservation of literal types."""

import unittest

from primitive_db.parser import parse_command, parse_set, parse_values, parse_where


def test_string_literals_keep_spaces_punctuation_and_boolean_text():
    assert parse_values('("Анна, SQL (where = set)", "true", "28", false, -3)') == [
        "Анна, SQL (where = set)",
        "true",
        "28",
        False,
        -3,
    ]


def test_escaped_quotes_slashes_and_empty_strings():
    assert parse_values(r"""("A \"quote\"", "C:\\data", '', 'O\'Brien')""") == [
        'A "quote"',
        "C:\\data",
        "",
        "O'Brien",
    ]


def test_keywords_inside_strings_are_values():
    command = parse_command('update users set name = "where" where name = "set"')
    assert command["set"] == {"name": "where"}
    assert command["where"] == {"name": "set"}


def test_multiple_conditions_and_assignments():
    assert parse_where('age=28 AND name="Сергей"') == {"age": 28, "name": "Сергей"}
    assert parse_set("age=29, is_active=false") == {"age": 29, "is_active": False}


def test_optional_where_and_case_insensitive_commands():
    assert parse_command("SELECT FROM users") == {
        "operation": "select",
        "table": "users",
        "where": None,
    }
    assert parse_command("  ") == {"operation": "empty"}


def test_bad_syntax_is_rejected():
    invalid = [
        "help extra",
        "exit extra",
        "info",
        "list_tables extra",
        "create_table users",
        "insert into users values (Anna, 28, true)",
        'insert into users values ("Anna" 28)',
        'insert into users values ("Anna",)',
        'insert into users values ("Anna", 1.5)',
        'insert into users values ("unfinished)',
        "select from users where",
        "delete from users",
        "update users set age=1",
        "select from ../users",
        "select from users where age=1 OR age=2",
        "not_a_command",
        "select from users where age=1 and age=2",
    ]
    for text in invalid:
        try:
            parse_command(text)
        except ValueError:
            continue
        raise AssertionError(f"Invalid command accepted: {text}")


def test_literal_placeholder_collision():
    text = '("__db_literal_0__", "#__db_literal_1__", "+1", +1)'
    assert parse_values(text) == ["__db_literal_0__", "#__db_literal_1__", "+1", 1]


def test_where_can_be_a_column_name():
    parsed = parse_command('update users set where = "new" where ID = 1')
    assert parsed["set"] == {"where": "new"}


def test_quoted_identifiers_are_rejected():
    for command in ['info "users"', 'select from users where "age" = 28']:
        try:
            parse_command(command)
        except ValueError:
            continue
        raise AssertionError(f"Quoted identifier accepted: {command}")


def load_tests(_loader, _tests, _pattern):
    """Expose ordinary test functions to unittest without defining classes."""
    return unittest.TestSuite(
        unittest.FunctionTestCase(func)
        for name, func in globals().items()
        if name.startswith("test_")
    )
