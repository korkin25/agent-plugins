"""Автодополнение слов по префиксу с ранжированием по весу."""


class _Node:
    __slots__ = ("children", "score")

    def __init__(self):
        self.children = {}
        self.score = 0


class Autocomplete:
    """Словарь слов с накопленными весами и подсказками по префиксу.

    Слово — любая непустая строка ``str``; регистр различается (``"Мир"`` и ``"мир"`` — разные слова), никакой
    нормализации не делается. У каждого слова есть счёт: сумма весов всех его добавлений после последнего удаления.
    Слово, которого нет в словаре, имеет счёт 0.
    """

    def __init__(self):
        self._root = _Node()
        self._size = 0
        self._order = []

    def add(self, word, weight=1):
        """Добавить к счёту слова ``word`` вес ``weight``; новое слово начинает со счёта 0.

        ``word`` должно быть непустой строкой, ``weight`` — целым числом ``int`` не меньше 1; иначе ``ValueError``,
        и словарь не меняется.
        """
        if not isinstance(word, str) or not word:
            raise ValueError("слово должно быть непустой строкой")
        if not isinstance(weight, int) or isinstance(weight, bool) or weight < 1:
            raise ValueError("вес должен быть целым числом не меньше 1")
        node = self._root
        for char in word:
            node = node.children.setdefault(char, _Node())
        if node.score == 0:
            self._size += 1
            if word in self._order:
                self._order.remove(word)
            self._order.append(word)
        node.score += weight

    def remove(self, word):
        """Удалить слово ``word`` целиком (его счёт становится 0) и вернуть ``True``.

        Если такого слова нет, вернуть ``False``. Другие слова, в том числе начинающиеся с ``word``, не меняются.
        """
        node = self._find(word)
        if node is None or node.score == 0:
            return False
        node.score = 0
        self._size -= 1
        return True

    def score(self, word):
        """Текущий счёт слова ``word`` (0, если слова нет)."""
        node = self._find(word)
        return 0 if node is None else node.score

    def complete(self, prefix, k=10):
        """Вернуть список не более чем из ``k`` слов, начинающихся с ``prefix``.

        Само слово ``prefix`` тоже подходит, если оно есть в словаре; пустой префикс подходит ко всем словам.
        Порядок: по счёту по убыванию, при равном счёте — по возрастанию самих строк в обычном сравнении ``str``
        (по кодам символов; например, ``"ё"`` идёт после ``"я"``, а заглавные буквы — раньше строчных). Берутся
        первые ``k`` слов этого порядка. При ``k <= 0`` результат — пустой список.
        """
        if k <= 0:
            return []
        start = self._find(prefix)
        if start is None:
            return []
        found = []
        for text in self._order:
            if text.startswith(prefix) and self.score(text):
                found.append((-self.score(text), text))
        found.sort(key=lambda item: item[0])
        return [text for _, text in found[:k]]

    def __len__(self):
        """Количество слов в словаре."""
        return self._size

    def _find(self, text):
        node = self._root
        for char in text:
            node = node.children.get(char)
            if node is None:
                return None
        return node
