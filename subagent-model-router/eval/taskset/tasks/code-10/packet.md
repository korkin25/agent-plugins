TASK: Реализуй класс `Autocomplete` в {workdir}/autocomplete.py так, чтобы он соответствовал спецификации в docstring модуля, класса и методов.
WORKDIR: {workdir}
READ: {workdir}/autocomplete.py (спецификация — в docstring); {workdir}/tests/test_visible.py.
EDIT: {workdir}/autocomplete.py. Можно добавлять свои тесты в {workdir}/tests/; больше ничего не менять.
CHECKS: `cd {workdir} && python3 -m unittest discover -s tests -v` должен проходить. Видимые тесты — лишь небольшой пример, а не приёмочный набор: модуль принимается по всей спецификации из docstring.
OUTPUT: {workdir}/autocomplete.py с реализованным `Autocomplete`: Python 3.11, только стандартная библиотека, имена класса и методов и их сигнатуры без изменений, без вывода на экран и без чтения или записи файлов.
MUST_NOT: переименовывать класс или методы и менять их сигнатуры; добавлять сторонние зависимости.
