TASK: Реализуй функции `is_valid` и `check_digit` в {workdir}/luhn.py так, чтобы они соответствовали спецификации в docstring модуля и функций.
WORKDIR: {workdir}
READ: {workdir}/luhn.py (спецификация — в docstring); {workdir}/tests/test_visible.py.
EDIT: {workdir}/luhn.py. Можно добавлять свои тесты в {workdir}/tests/; больше ничего не менять.
CHECKS: `cd {workdir} && python3 -m unittest discover -s tests -v` должен проходить. Видимые тесты — лишь небольшой пример, а не приёмочный набор: модуль принимается по всей спецификации из docstring.
OUTPUT: {workdir}/luhn.py с реализованными `is_valid` и `check_digit`: Python 3.11, только стандартная библиотека, имена и сигнатуры функций без изменений, без вывода на экран и без чтения или записи файлов.
MUST_NOT: переименовывать функции или менять их сигнатуры; добавлять сторонние зависимости.
