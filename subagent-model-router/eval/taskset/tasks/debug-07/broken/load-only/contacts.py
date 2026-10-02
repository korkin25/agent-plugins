"""Список контактов из CSV-выгрузки.

    python3 contacts.py export.csv                  # все контакты, по одному в строке: «Имя <email>»
    python3 contacts.py export.csv --city казань    # только контакты из этого города
    python3 contacts.py export.csv --check          # только проверить заголовок: печатает «ok»

Файл — CSV в кодировке UTF-8, в том числе сохранённый из Excel как «CSV UTF-8». Первая строка — заголовок;
в нём должны быть колонки name, email и city в любом порядке, остальные колонки не важны. Пробелы по краям
имён колонок и значений не учитываются, пустые строки файла пропускаются.
Контакты печатаются в порядке строк файла. Город в --city сравнивается без учёта регистра.
Если в заголовке нет нужных колонок, утилита (и в режиме --check тоже) печатает в stderr
`ошибка: нет колонок: <имена через запятую с пробелом, в порядке name, email, city>` и завершается с кодом 1.
"""
import argparse
import csv
import sys

COLUMNS = ("name", "email", "city")


class FormatError(ValueError):
    pass


def check_header(header: list[str]) -> None:
    """FormatError, если в заголовке (списке имён колонок) нет какой-то из колонок name, email, city."""
    missing = [column for column in COLUMNS if column not in header]
    if missing:
        raise FormatError("нет колонок: " + ", ".join(missing))


def read_header(path: str) -> list[str]:
    """Имена колонок из первой строки файла, без пробелов по краям."""
    with open(path, encoding="utf-8", newline="") as handle:
        row = next(csv.reader(handle), [])
    return [cell.strip() for cell in row]


def load(path: str) -> list[dict[str, str]]:
    """Контакты файла в порядке строк: словари с ключами name, email, city. FormatError при плохом заголовке."""
    with open(path, encoding="utf-8-sig", newline="") as handle:
        reader = csv.reader(handle)
        header = [cell.strip() for cell in next(reader, [])]
        check_header(header)
        index = {column: header.index(column) for column in COLUMNS}
        contacts = []
        for row in reader:
            if not any(cell.strip() for cell in row):
                continue
            contacts.append({column: row[index[column]].strip() for column in COLUMNS})
    return contacts


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Список контактов из CSV-выгрузки.")
    parser.add_argument("path")
    parser.add_argument("--city", help="только контакты из этого города")
    parser.add_argument("--check", action="store_true", help="только проверить заголовок")
    args = parser.parse_args(argv)
    try:
        if args.check:
            check_header(read_header(args.path))
            print("ok")
            return 0
        contacts = load(args.path)
    except FormatError as exc:
        print(f"ошибка: {exc}", file=sys.stderr)
        return 1
    for contact in contacts:
        if args.city is None or contact["city"].casefold() == args.city.casefold():
            print(f"{contact['name']} <{contact['email']}>")
    return 0


if __name__ == "__main__":
    sys.exit(main())
