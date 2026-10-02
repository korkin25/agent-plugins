"""Wrap the paragraphs of a text file to a given width.

    python3 wrap.py notes.txt --width 40             # each paragraph wrapped to 40 columns
    python3 wrap.py notes.txt --width 40 --bullets   # each paragraph as a "- " bullet, later lines indented "  "

Paragraphs are separated by blank lines; inside a paragraph, line breaks and runs of whitespace only separate
words. The paragraphs are printed in order with one blank line between them.
"""
import argparse
import sys


def wrap(text: str, width: int, first_prefix: str = "", rest_prefix: str = "") -> list[str]:
    """Fill the words of `text` into lines of at most `width` characters and return the lines.

    The first line starts with `first_prefix`, every later line with `rest_prefix`; the prefix counts towards
    the width. Words are separated by one space. Lines are filled greedily: a line takes the next word whenever
    the word still fits. A word that does not fit even on a line of its own stays whole and gets a line to
    itself. Text without words gives no lines.
    """
    lines = []
    prefix = first_prefix
    line_words = []
    line_len = len(prefix)
    for word in text.split():
        if line_words and line_len + 1 + len(word) > width:
            lines.append(prefix + " ".join(line_words))
            prefix = rest_prefix
            line_words = []
            line_len = 0
        line_len += len(word) + (1 if line_words else 0)
        line_words.append(word)
    if line_words:
        lines.append(prefix + " ".join(line_words))
    return lines


def paragraphs(text: str) -> list[str]:
    """The paragraphs of `text`: runs of non-blank lines, each joined into one string."""
    result, current = [], []
    for line in text.splitlines():
        if line.strip():
            current.append(line.strip())
        elif current:
            result.append(" ".join(current))
            current = []
    if current:
        result.append(" ".join(current))
    return result


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Wrap the paragraphs of a text file.")
    parser.add_argument("path")
    parser.add_argument("--width", type=int, default=72)
    parser.add_argument("--bullets", action="store_true", help='start each paragraph with "- "')
    args = parser.parse_args(argv)
    with open(args.path, encoding="utf-8") as handle:
        text = handle.read()
    prefixes = ("- ", "  ") if args.bullets else ("", "")
    blocks = ["\n".join(wrap(paragraph, args.width, *prefixes)) for paragraph in paragraphs(text)]
    if blocks:
        print("\n\n".join(blocks))
    return 0


if __name__ == "__main__":
    sys.exit(main())
