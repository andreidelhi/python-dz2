"""Parse database commands while preserving quoted strings and their types."""

import json
import shlex

from primitive_db.utils import validate_name


def _protect_strings(text):
    """Replace quoted literals with unique tokens before shell tokenization."""
    prefix = "__db_literal_"
    while prefix in text:
        prefix = "_" + prefix
    rewritten = []
    literals = {}
    index = 0
    while index < len(text):
        quote = text[index]
        if quote not in {"'", '"'}:
            rewritten.append(quote)
            index += 1
            continue
        start = index
        index += 1
        value = []
        while index < len(text) and text[index] != quote:
            if text[index] == "\\":
                index += 1
                if index >= len(text):
                    raise ValueError("Незавершённая escape-последовательность")
                if quote == "'" and text[index] not in {"'", "\\"}:
                    value.append("\\")
            value.append(text[index])
            index += 1
        if index >= len(text):
            raise ValueError("Не закрыты кавычки строкового значения")
        index += 1
        literal = json.loads(text[start:index]) if quote == '"' else "".join(value)
        token = f"{prefix}{len(literals)}__"
        literals[token] = literal
        rewritten.extend([" ", token, " "])
    return "".join(rewritten), literals


def _tokenize(text):
    """Use shlex for command tokens without losing string-literal information."""
    text, literals = _protect_strings(text)
    lexer = shlex.shlex(text, posix=True, punctuation_chars="(),=")
    lexer.whitespace_split = True
    lexer.commenters = ""
    tokens = []
    for token in lexer:
        if all(char in "(),=" for char in token):
            tokens.extend(token)
        else:
            tokens.append(token)
    return tokens, literals


def _value(token, literals):
    """Parse a quoted string, integer or true/false literal."""
    if token in literals:
        return literals[token]
    if token.lower() in {"true", "false"}:
        return token.lower() == "true"
    digits = token[1:] if token.startswith(("+", "-")) else token
    if digits and digits.isdecimal():
        return int(token)
    raise ValueError(f"Некорректное значение: {token}. Строки заключайте в кавычки.")


def _identifier(token, literals):
    """Accept unquoted names and reject string-literal placeholders."""
    if token in literals:
        raise ValueError("Имена таблиц и столбцов указывайте без кавычек")
    return validate_name(token)


def _assignments(tokens, literals, separator):
    """Parse one or more column=value assignments with a given separator."""
    result = {}
    while tokens:
        if len(tokens) < 3 or tokens[1] != "=":
            raise ValueError("Ожидается условие вида столбец = значение")
        name = _identifier(tokens[0], literals)
        if name in result:
            raise ValueError(f"Столбец {name} указан повторно")
        result[name] = _value(tokens[2], literals)
        tokens = tokens[3:]
        if tokens:
            if tokens[0].lower() != separator or len(tokens) == 1:
                raise ValueError(f"Ожидается разделитель {separator}")
            tokens = tokens[1:]
    if not result:
        raise ValueError("Условие не может быть пустым")
    return result


def parse_where(text):
    """Return a dictionary for equality conditions joined with AND."""
    tokens, literals = _tokenize(text)
    return _assignments(tokens, literals, "and")


def parse_set(text):
    """Return a dictionary for comma-separated SET assignments."""
    tokens, literals = _tokenize(text)
    return _assignments(tokens, literals, ",")


def _values(tokens, literals):
    """Parse a parenthesized, comma-separated list of typed literals."""
    if len(tokens) < 2 or tokens[0] != "(" or tokens[-1] != ")":
        raise ValueError("Ожидается values (значение1, значение2, ...)")
    tokens = tokens[1:-1]
    if not tokens:
        return []
    values = []
    for index, token in enumerate(tokens):
        if index % 2:
            if token != ",":
                raise ValueError("Значения нужно разделять запятыми")
        else:
            values.append(_value(token, literals))
    if len(tokens) % 2 == 0:
        raise ValueError("После запятой ожидается значение")
    return values


def parse_values(text):
    """Return typed values from a parenthesized VALUES expression."""
    tokens, literals = _tokenize(text)
    return _values(tokens, literals)


def parse_command(text):
    """Parse a complete command and reject invalid or incomplete syntax."""
    tokens, literals = _tokenize(text.strip())
    if not tokens:
        return {"operation": "empty"}
    operation = tokens[0].lower()
    args = tokens[1:]
    result = {"operation": operation}
    if operation in {"help", "exit", "list_tables"} and not args:
        return result
    if operation == "create_table" and len(args) >= 2:
        result.update(table=_identifier(args[0], literals), columns=args[1:])
        return result
    if operation in {"drop_table", "info"} and len(args) == 1:
        result["table"] = _identifier(args[0], literals)
        return result
    if operation == "insert" and len(args) >= 4:
        if args[0].lower() == "into" and args[2].lower() == "values":
            result.update(
                table=_identifier(args[1], literals), values=_values(args[3:], literals)
            )
            return result
    if operation in {"select", "delete"} and len(args) >= 2:
        if args[0].lower() == "from":
            result["table"] = _identifier(args[1], literals)
            if operation == "select" and len(args) == 2:
                result["where"] = None
                return result
            if len(args) >= 4 and args[2].lower() == "where":
                result["where"] = _assignments(args[3:], literals, "and")
                return result
    if operation == "update" and len(args) >= 9 and args[1].lower() == "set":
        where_index = next(
            (i for i in range(5, len(args), 4) if args[i].lower() == "where"), None
        )
        if where_index is not None:
            result.update(
                table=_identifier(args[0], literals),
                set=_assignments(args[2:where_index], literals, ","),
                where=_assignments(args[where_index + 1 :], literals, "and"),
            )
            return result
    known = {
        "help",
        "exit",
        "list_tables",
        "create_table",
        "drop_table",
        "info",
        "insert",
        "select",
        "update",
        "delete",
    }
    if operation not in known:
        raise ValueError(f"Функции {tokens[0]} нет. Попробуйте снова.")
    raise ValueError("Некорректное значение аргументов. Попробуйте снова.")
