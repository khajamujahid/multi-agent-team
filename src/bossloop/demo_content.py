"""The rehearsed offline job: a small text module whose first draft fails on purpose."""

from __future__ import annotations

DEMO_TASK = """Build a Python module named textkit with three functions:

1. word_count(text: str) -> int
   Count words. A word is a maximal run of letters or digits.
   "hello, world" has 2 words. "hello,world" has 2 words. "one-two" has 2 words.

2. unique_words(text: str) -> list[str]
   Return unique words in first-seen order, compared case-insensitively, stored lowercase.
   "One one TWO two Three" -> ["one", "two", "three"].

3. is_palindrome(text: str) -> bool
   True when the letters and digits read the same forward and backward.
   Ignore case, spaces, and punctuation.
   "A man, a plan, a canal: Panama" -> True.
   "race a car" -> False.
"""

DEMO_PLAN = (
    "Ship one module, textkit.py, with three pure functions: word_count, "
    "unique_words, and is_palindrome. No network, no files, no extra "
    "dependencies. A word is a maximal run of letters or digits, so punctuation "
    "splits words and is not itself a word. Unique words are lowercase and keep "
    "first-seen order. A palindrome compares letters and digits only, ignoring "
    "case. test_textkit.py is the contract. It is frozen. The coder may not edit it."
)

DEMO_CRITERIA = [
    "word_count counts maximal runs of letters or digits and treats punctuation as a separator.",
    "unique_words returns lowercase words in first-seen order.",
    "is_palindrome ignores case, spaces, and punctuation.",
    "The coder may change textkit.py only.",
    "Done means the frozen pytest suite exits 0.",
]

DEMO_BOSS_MESSAGE = (
    "Work order accepted. The module is textkit. I am freezing the acceptance "
    "tests now. Coder, you may edit textkit.py only. Tester, you run that suite "
    "as written and you report the counts you actually observed. I will not call "
    "this done while the suite is red."
)

BUGGY_MODULE = '''def word_count(text: str) -> int:
    if not text or not text.strip():
        return 0
    return len(text.split())


def unique_words(text: str) -> list[str]:
    seen: list[str] = []
    for word in text.split():
        cleaned = word.strip(".,!?:;\\"'()[]")
        if cleaned and cleaned not in seen:
            seen.append(cleaned)
    return seen


def is_palindrome(text: str) -> bool:
    return text == text[::-1]
'''

FIXED_MODULE = '''import re

_TOKEN = re.compile(r"[A-Za-z0-9]+")


def _words(text: str) -> list[str]:
    return _TOKEN.findall(text or "")


def word_count(text: str) -> int:
    return len(_words(text))


def unique_words(text: str) -> list[str]:
    seen: list[str] = []
    for word in _words(text):
        lowered = word.lower()
        if lowered not in seen:
            seen.append(lowered)
    return seen


def is_palindrome(text: str) -> bool:
    chars = [ch.lower() for ch in (text or "") if ch.isalnum()]
    return chars == chars[::-1]
'''

ACCEPTANCE_TESTS = '''from textkit import is_palindrome, unique_words, word_count


def test_word_count_empty():
    assert word_count("") == 0
    assert word_count("   ") == 0


def test_word_count_punctuation_is_not_a_word():
    assert word_count("hello, world") == 2
    assert word_count("hello,world") == 2
    assert word_count("one-two") == 2


def test_unique_words_are_lowercase_and_ordered():
    assert unique_words("One one TWO two Three") == ["one", "two", "three"]


def test_palindrome_ignores_case_space_and_punctuation():
    assert is_palindrome("A man, a plan, a canal: Panama") is True


def test_palindrome_rejects_a_near_miss():
    assert is_palindrome("race a car") is False


def test_palindrome_simple_words():
    assert is_palindrome("racecar") is True
    assert is_palindrome("hello") is False
'''

CODER_DRAFT_MESSAGE = (
    "Submitted textkit.py. Words are split on whitespace, unique words keep the "
    "spelling I first saw, and a palindrome is a raw string compared with its reverse."
)

CODER_FIX_MESSAGE = (
    "Revised textkit.py only. Words are now maximal runs of letters and digits, "
    "unique words are stored lowercase in first-seen order, and palindromes compare "
    "letters and digits after lowercasing. The frozen tests were not touched."
)


def is_demo_task(task: str) -> bool:
    folded = " ".join(task.lower().split())
    required = ("textkit", "word_count", "unique_words", "is_palindrome")
    return all(token in folded for token in required)
