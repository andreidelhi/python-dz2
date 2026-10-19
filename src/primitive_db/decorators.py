"""Reusable error handling for database operations."""


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
