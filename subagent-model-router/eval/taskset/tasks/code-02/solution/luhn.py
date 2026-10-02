"""Контрольная цифра по алгоритму Луна.

Алгоритм Луна: цифры номера нумеруются справа налево, начиная с единицы. Каждая цифра на чётной позиции
(вторая справа, четвёртая справа и т. д.) удваивается; если результат больше 9, из него вычитается 9. Номер
корректен, если сумма всех полученных цифр делится на 10.

Цифры здесь — только ASCII-символы ``0``–``9``.
"""

DIGITS = "0123456789"


def _luhn_sum(digits: str) -> int:
    total = 0
    for position, char in enumerate(reversed(digits), start=1):
        value = DIGITS.index(char)
        if position % 2 == 0:
            value *= 2
            if value > 9:
                value -= 9
        total += value
    return total


def is_valid(number: str) -> bool:
    """Проверить номер по алгоритму Луна.

    ``number`` может содержать ASCII-цифры и пробелы; пробелы игнорируются. Номер корректен, если после удаления
    пробелов в нём не меньше двух цифр, нет других символов и сумма по алгоритму Луна делится на 10.
    Возвращает ``True`` или ``False``; исключений не бросает.
    """
    if not isinstance(number, str):
        return False
    digits = number.replace(" ", "")
    if len(digits) < 2 or any(char not in DIGITS for char in digits):
        return False
    return _luhn_sum(digits) % 10 == 0


def check_digit(payload: str) -> str:
    """Вычислить контрольную цифру для ``payload``.

    ``payload`` — непустая строка только из ASCII-цифр (пробелы не допускаются). Возвращает одну цифру
    (строку длины 1), после дописывания которой справа номер ``payload + цифра`` становится корректным.
    Для любых других значений ``payload`` бросает ``ValueError``.
    """
    if not isinstance(payload, str) or not payload or any(char not in DIGITS for char in payload):
        raise ValueError("payload must be a non-empty string of ASCII digits")
    return DIGITS[(10 - _luhn_sum(payload + "0") % 10) % 10]
