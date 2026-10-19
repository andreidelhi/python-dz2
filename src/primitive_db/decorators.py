"""Reusable error handling for database operations."""

import time

import prompt

from primitive_db.constants import CACHE_LIMIT


def handle_db_errors(func):
    """Print an understandable database error and return None on failure."""

    def wrapper(*args, **kwargs):
        """Run the wrapped action inside the shared error boundary."""
        try:
            return func(*args, **kwargs)
        except FileNotFoundError:
            print("Ошибка: Файл данных не найден. Возможно, база не инициализирована.")
        except KeyError as error:
            message = error.args[0] if error.args else "Таблица или столбец не найден"
            print(f"Ошибка: {message}")
        except ValueError as error:
            print(f"Ошибка валидации: {error}")
        except OSError as error:
            print(f"Ошибка работы с файлами: {error}")
        return None

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    wrapper.__wrapped__ = func
    return wrapper


def confirm_action(action_name):
    """Require an explicit y before running a destructive action."""

    def decorator(func):
        """Decorate a function with an action-specific confirmation prompt."""

        def wrapper(*args, **kwargs):
            """Return None without changing data if the user declines."""
            question = f'Вы уверены, что хотите выполнить "{action_name}"? [y/n]: '
            answer = prompt.string(question, empty=True)
            if answer != "y":
                print("Операция отменена.")
                return None
            return func(*args, **kwargs)

        wrapper.__name__ = func.__name__
        wrapper.__doc__ = func.__doc__
        wrapper.__wrapped__ = func
        return wrapper

    return decorator


def log_time(func):
    """Print elapsed wall time measured with time.monotonic()."""

    def wrapper(*args, **kwargs):
        """Measure a completed call without changing its return value."""
        started = time.monotonic()
        result = func(*args, **kwargs)
        elapsed = time.monotonic() - started
        print(f"Функция {func.__name__} выполнилась за {elapsed:.3f} секунд.")
        return result

    wrapper.__name__ = func.__name__
    wrapper.__doc__ = func.__doc__
    wrapper.__wrapped__ = func
    return wrapper


def create_cacher():
    """Return a closure which caches values by key and bounds its memory use."""
    cache = {}

    def cache_result(key, value_func):
        """Compute a missing value once, and reuse it on repeated queries."""
        if key not in cache:
            value = value_func()
            if len(cache) >= CACHE_LIMIT:
                del cache[next(iter(cache))]
            cache[key] = value
        return cache[key]

    return cache_result
