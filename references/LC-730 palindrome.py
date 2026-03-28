from __future__ import annotations

from functools import lru_cache
import random

MOD = 10**9 + 7


def _build_same_char_links(s: str) -> tuple[list[int], list[int]]:
    """
    Build links for O(1) inner equal-char lookup.
    prev_same[i] = max j < i with s[j] == s[i], else -1
    next_same[i] = min j > i with s[j] == s[i], else -1
    """
    n = len(s)
    prev_same = [-1] * n
    next_same = [-1] * n

    last_pos: dict[str, int] = {}
    for i, ch in enumerate(s):
        prev_same[i] = last_pos.get(ch, -1)
        last_pos[ch] = i

    next_pos: dict[str, int] = {}
    for i in range(n - 1, -1, -1):
        ch = s[i]
        next_same[i] = next_pos.get(ch, -1)
        next_pos[ch] = i

    return prev_same, next_same


def str_first_inner_eq_id(
    s: str, i: int, j: int, next_same: list[int]
) -> int | None:
    """
    logic: str.first_inner_eq_id: {str, i, j} => id
      id = min{ k | str[k] = str[i] | i < k < j }, or null
    """
    k = next_same[i]
    if k != -1 and k < j:
        return k
    return None


def str_last_inner_eq_id(
    s: str, i: int, j: int, prev_same: list[int]
) -> int | None:
    """
    logic: str.last_inner_eq_id: {str, i, j} => id
      id = max{ k | str[k] = str[i] | i < k < j }, or null
    """
    k = prev_same[j]
    if k != -1 and k > i:
        return k
    return None


def str_pal_subseqs_size_interval(s: str, i: int, j: int) -> int:
    """
    logic: str.pal_subseqs_size: {str, i, j} => size
    """
    n = len(s)
    if n == 0:
        return 0

    prev_same, next_same = _build_same_char_links(s)

    @lru_cache(maxsize=None)
    def dp(l: int, r: int) -> int:
        # |- i > j
        if l > r:
            return 0
        # |- i = j
        if l == r:
            return 1

        # |- i < j
        if s[l] != s[r]:
            v1 = dp(l + 1, r)
            v2 = dp(l, r - 1)
            v3 = dp(l + 1, r - 1)
            return (v1 + v2 - v3) % MOD

        # |- s[i] = s[j]
        inner = dp(l + 1, r - 1)
        left_id = str_first_inner_eq_id(s, l, r, next_same)
        right_id = str_last_inner_eq_id(s, l, r, prev_same)

        # |- left_id = null
        if left_id is None:
            return (2 * inner + 2) % MOD

        # |- left_id = right_id
        if left_id == right_id:
            return (2 * inner + 1) % MOD

        # |- left_id < right_id
        dup = dp(left_id + 1, right_id - 1)
        return (2 * inner - dup) % MOD

    return dp(i, j) % MOD


def str_pal_subseqs_size(s: str) -> int:
    """
    logic: str.pal_subseqs_size: str => size
      size = str.pal_subseqs_size(0, str.size - 1)
    """
    if not s:
        return 0
    return str_pal_subseqs_size_interval(s, 0, len(s) - 1) % MOD


def _brute_force_pal_subseqs_size(s: str) -> int:
    """
    Definition checker for small strings:
      size = {subseq | subseq != "", subseq.is_palindrome, subseq in s.subseqs}.size
    """
    n = len(s)
    pal_set: set[str] = set()
    for mask in range(1, 1 << n):
        chars: list[str] = []
        for i in range(n):
            if (mask >> i) & 1:
                chars.append(s[i])
        subseq = "".join(chars)
        if subseq == subseq[::-1]:
            pal_set.add(subseq)
    return len(pal_set)


class Solution:
    def countPalindromicSubsequences(self, s: str) -> int:
        # Return count modulo MOD (LeetCode 730 requirement).
        return str_pal_subseqs_size(s)


if __name__ == "__main__":
    fixed_cases = {
        "": 0,
        "a": 1,
        "aa": 2,      # "a", "aa"
        "aaa": 3,     # "a", "aa", "aaa"
        "abcd": 4,    # single-char palindromes only
        "bccb": 6,    # "b", "c", "bb", "cc", "bcb", "bccb"
        "abca": 6,
        "abcdabcdabcdabcdabcdabcdabcdabcddcbadcbadcbadcbadcbadcbadcbadcba": 104860361
    }
    for text, expected in fixed_cases.items():
        got = str_pal_subseqs_size(text)
        print(f"fixed {text!r}: {got}")
        assert got == expected, (text, expected, got)

    # Random definition cross-check (small n).
    rng = random.Random(0)
    alphabet = "abcd"
    for _ in range(200):
        n = rng.randint(0, 10)
        text = "".join(rng.choice(alphabet) for _ in range(n))
        got = str_pal_subseqs_size(text)
        want = _brute_force_pal_subseqs_size(text)
        assert got == want, (text, got, want)

    print("All checks passed.")
