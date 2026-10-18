"""Interactive command loop."""

import prompt


def print_help():
    """Print the available commands."""
    print("<command> exit - выйти из программы")
    print("<command> help - справочная информация")


def welcome():
    """Run the initial help-and-exit command loop."""
    print("***Примитивная база данных***")
    print_help()
    while True:
        try:
            command = prompt.string("Введите команду: ", empty=True)
        except (EOFError, KeyboardInterrupt):
            print("\nДо свидания!")
            return
        if not command:
            continue
        if command.strip() == "exit":
            print("До свидания!")
            return
        if command.strip() == "help":
            print_help()
        else:
            print(f"Функции {command} нет. Попробуйте снова.")


def run():
    """Start the database console."""
    welcome()
