"""test_oracle.py - proves trie.py against a brute-force reference.

Imports trie.py only (never app.py). Run with `python test_oracle.py`
(or `pytest test_oracle.py`).

Part 1: hand-written cases using the seed data.
Part 2: random operations applied to the trie AND to a plain-dict reference,
        compared after every step (words, followers, accepted, every cache).
Part 3: save/load round trip and the fallback to seed data on a bad file.

The reference code below shares no code with trie.py. It shares only the
agreed rules: lowercase words, popularity-descending then alphabetical order,
two follower levels (last two words, then last word), followers first, then
the dictionary fill.
"""

import json
import os
import random
import tempfile
import time

from trie import Autocomplete

SEEDS = 100       # random runs per cache size
STEPS = 150       # operations per run
ALPHABET = "abc"  # tiny alphabet: many shared prefixes and prefix-words

SEED_WORDS = {
    "pizza": 20, "pasta": 15, "pie": 5,
    "apple": 30, "pineapple": 100, "peach": 3,
}
SEED_FOLLOWERS = {"pasta": 3, "apple": 2, "pizza": 1}


# ----------------------------------------------------------------------
# reference implementation (brute force, plain dicts)
# ----------------------------------------------------------------------

def brute_top_k(words, prefix, k):
    matches = [(w, p) for w, p in words.items() if w.startswith(prefix)]
    matches.sort(key=lambda e: (-e[1], e[0]))
    return matches[:k]


def brute_context_keys(context_words):
    keys = []
    if len(context_words) >= 2:
        keys.append(" ".join(context_words[-2:]))
    if len(context_words) >= 1:
        keys.append(context_words[-1])
    return keys


def brute_next_word(words, followers, context_words, partial, k):
    result = []
    used = set()
    for key in brute_context_keys(context_words):
        level = [
            (w, c, "follower")
            for w, c in followers.get(key, {}).items()
            if w in words and w.startswith(partial) and w not in used
        ]
        level.sort(key=lambda e: (-e[1], e[0]))
        result += level
        used.update(e[0] for e in level)
    # fill from the WHOLE dictionary, not a capped list
    for w, p in brute_top_k(words, partial, len(words)):
        if w not in used:
            result.append((w, p, "popular"))
    return result[:k]


class Ref:
    """The oracle's data: three plain dicts."""

    def __init__(self):
        self.words = {}
        self.followers = {}
        self.accepted = {}

    def set_word(self, word, popularity):
        old = self.words.get(word)
        self.words[word] = popularity
        return old

    def delete_word(self, word):
        return self.words.pop(word, None)   # followers/accepted are kept

    def accept(self, context_words, word):
        if word not in self.words:
            return None
        keys = brute_context_keys(context_words)
        if not keys:
            return None
        for key in keys:
            table = self.followers.setdefault(key, {})
            table[word] = table.get(word, 0) + 1
        self.accepted[word] = self.accepted.get(word, 0) + 1
        return self.followers[keys[0]][word]


def seed_ref():
    ref = Ref()
    ref.words = dict(SEED_WORDS)
    ref.followers = {"i like": dict(SEED_FOLLOWERS), "like": dict(SEED_FOLLOWERS)}
    ref.accepted = dict(SEED_FOLLOWERS)
    return ref


# ----------------------------------------------------------------------
# comparison helpers
# ----------------------------------------------------------------------

def expect(actual, expected, what):
    if actual != expected:
        raise AssertionError(
            f"{what}\n  trie:   {actual!r}\n  oracle: {expected!r}")


def walk(node, prefix=""):
    yield node, prefix
    for ch in sorted(node.children):
        yield from walk(node.children[ch], prefix + ch)


def check_structure(ac, ref, K):
    """Every node's cache, every stored word, and no dead-end nodes."""
    stored = {}
    for node, prefix in walk(ac.root):
        if node.popularity is not None:
            stored[prefix] = node.popularity
        if prefix and node.popularity is None and not node.children:
            raise AssertionError(f"dead-end node left in trie: {prefix!r}")
        subtree = {w: p for w, p in ref.words.items() if w.startswith(prefix)}
        expect(node.top, brute_top_k(subtree, "", K), f"cache at node {prefix!r}")
    expect(stored, ref.words, "words reachable in the trie")


def random_word(rng, min_len=1, max_len=4):
    return "".join(rng.choice(ALPHABET) for _ in range(rng.randint(min_len, max_len)))


def random_context(rng, ref):
    if ref.followers and rng.random() < 0.6:
        words = rng.choice(sorted(ref.followers)).split(" ")
        if rng.random() < 0.3:                      # longer than two words
            words = [random_word(rng, 1, 2)] + words
        return words
    return [random_word(rng, 1, 2) for _ in range(rng.randint(0, 3))]


def check_all(ac, ref, K, rng, ever_used):
    expect(ac.words, ref.words, "flat map")
    expect(ac.followers, ref.followers, "follower tables")
    expect(ac.accepted, ref.accepted, "accepted map")
    check_structure(ac, ref, K)

    prefixes = {"", "zz"}
    for w in ever_used:
        for i in range(1, len(w) + 1):
            prefixes.add(w[:i])
    ks = range(1, K + 1) if K <= 5 else sorted({1, 2, 3, K // 2, K - 1, K})
    for p in sorted(prefixes):
        full = brute_top_k(ref.words, p, K)
        for k in ks:
            expect(ac.top_k(p, k), full[:k], f"top_k({p!r}, {k})")

    for _ in range(6):
        context = random_context(rng, ref)
        partial = rng.choice(["", rng.choice(ALPHABET), random_word(rng, 1, 3)])
        k = rng.randint(1, K)
        expect(ac.next_word(context, partial, k),
               brute_next_word(ref.words, ref.followers, context, partial, k),
               f"next_word({context!r}, {partial!r}, {k})")


# ----------------------------------------------------------------------
# Part 1: hand-written cases (seed data from a missing file)
# ----------------------------------------------------------------------

def seeded(k=20):
    ac = Autocomplete(k=k)
    ac.load(os.path.join(tempfile.mkdtemp(), "data.json"))   # missing file -> seed
    return ac


def test_seed_prefix_queries():
    ac = seeded()
    expect(ac.words, SEED_WORDS, "seed words")
    assert ac.top_k("p", 5) == [("pineapple", 100), ("pizza", 20), ("pasta", 15),
                                ("pie", 5), ("peach", 3)]
    assert ac.top_k("p") == [("pineapple", 100)]                 # default k = 1
    assert ac.top_k("pi", 3) == [("pineapple", 100), ("pizza", 20), ("pie", 5)]
    assert ac.top_k("pa", 3) == [("pasta", 15)]                  # pasta is not under "pi"
    assert ac.top_k("xyz", 3) == []
    assert len(ac.top_k("p", 50)) == 5                           # fewer matches than k


def test_insert_change_overwrite_examples():
    ac = Autocomplete()
    assert ac.set_word("pizza", 10) is None                      # new word
    assert ac.set_word("pasta", 20) is None
    assert ac.set_word("pie", 5) is None
    assert ac.top_k("pi", 3) == [("pizza", 10), ("pie", 5)]
    assert ac.top_k("p", 3) == [("pasta", 20), ("pizza", 10), ("pie", 5)]

    ac.accept(["i", "like"], "pizza")                            # follow count 1
    assert ac.set_word("pizza", 30) == 10                        # increase
    assert ac.top_k("p", 3) == [("pizza", 30), ("pasta", 20), ("pie", 5)]
    assert ac.followers["i like"]["pizza"] == 1                  # follows unchanged

    assert ac.set_word("pizza", 15) == 30                        # overwrite, no duplicate
    assert ac.top_k("p", 3) == [("pasta", 20), ("pizza", 15), ("pie", 5)]
    assert len(ac.words) == 3
    assert [w for w, _ in ac.top_k("p", 10)].count("pizza") == 1


def test_decrease_brings_back_dropped_word():
    ac = Autocomplete(k=3)
    for w, p in [("pizza", 30), ("pasta", 20), ("pie", 5), ("peach", 3)]:
        ac.set_word(w, p)
    assert ac.top_k("p", 3) == [("pizza", 30), ("pasta", 20), ("pie", 5)]  # peach dropped
    ac.set_word("pizza", 1)
    assert ac.top_k("p", 3) == [("pasta", 20), ("pie", 5), ("peach", 3)]   # peach is back
    ac.set_word("peach", 40)                                     # increase
    assert ac.top_k("p", 1) == [("peach", 40)]


def test_delete():
    ac = seeded()
    assert ac.delete_word("pizza") == 20
    assert ac.top_k("piz", 3) == []
    assert "z" not in ac.root.children["p"].children["i"].children   # path pruned
    assert ac.top_k("pi", 3) == [("pineapple", 100), ("pie", 5)]
    assert ac.top_k("p", 5) == [("pineapple", 100), ("pasta", 15), ("pie", 5), ("peach", 3)]
    assert ac.delete_word("pizza") is None                       # already gone
    assert ac.delete_word("orange") is None                      # never existed
    assert "pizza" not in ac.words


def test_delete_word_that_is_a_prefix():
    ac = Autocomplete()
    ac.set_word("app", 5)
    ac.set_word("apple", 10)
    assert ac.top_k("app", 3) == [("apple", 10), ("app", 5)]     # "app" completes itself
    assert ac.delete_word("app") == 5
    assert ac.top_k("app", 3) == [("apple", 10)]                 # node kept for apple
    assert ac.delete_word("apple") == 10
    assert ac.top_k("a", 3) == []
    assert ac.root.children == {}                                # everything pruned


def test_zero_popularity_is_a_real_word():
    ac = seeded()
    assert ac.set_word("pea", 0) is None
    assert ac.top_k("p", 10)[-1] == ("pea", 0)                   # shown last
    assert ac.set_word("pea", 7) == 0                            # old is 0, not None
    assert ac.set_word("pea", 0) == 7
    assert ac.delete_word("pea") == 0


def test_ties_are_alphabetical():
    ac = Autocomplete()
    for w in ["c", "a", "b"]:
        ac.set_word(w, 5)
    assert ac.top_k("", 3) == [("a", 5), ("b", 5), ("c", 5)]


def test_next_word_followers_then_fill():
    ac = seeded()
    ctx = ["i", "like"]
    assert ac.next_word(ctx, "", 6) == [
        ("pasta", 3, "follower"), ("apple", 2, "follower"), ("pizza", 1, "follower"),
        ("pineapple", 100, "popular"), ("pie", 5, "popular"), ("peach", 3, "popular"),
    ]
    assert [w for w, _, _ in ac.next_word(ctx, "", 3)] == ["pasta", "apple", "pizza"]
    # test 9: pineapple (100) was never used after "i like", so it comes after
    assert ac.next_word(ctx, "p", 5) == [
        ("pasta", 3, "follower"), ("pizza", 1, "follower"),
        ("pineapple", 100, "popular"), ("pie", 5, "popular"), ("peach", 3, "popular"),
    ]


def test_next_word_backoff():
    ac = seeded()
    same = ac.next_word(["i", "like"], "", 3)
    assert ac.next_word(["yesterday", "i", "like"], "", 3) == same   # last two words
    assert ac.next_word(["we", "like"], "", 3) == same               # backs off to "like"
    assert ac.next_word(["i", "adore"], "", 3) == [                  # nothing seen: fill
        ("pineapple", 100, "popular"), ("apple", 30, "popular"), ("pizza", 20, "popular")]
    assert ac.next_word([], "piz", 3) == [("pizza", 20, "popular")]  # no context at all


def test_next_word_levels_are_strict_and_deduplicated():
    ac = Autocomplete()
    for w, p in [("x", 1), ("y", 2), ("z", 3)]:
        ac.set_word(w, p)
    ac.accept(["a", "b"], "x")                                   # "a b": x 1, "b": x 1
    for _ in range(3):
        ac.accept(["c", "b"], "y")                               # "c b": y 3, "b": y 3
    assert ac.next_word(["a", "b"], "", 5) == [
        ("x", 1, "follower"),      # level 1, although y has a higher count
        ("y", 3, "follower"),      # level 2; x is not repeated
        ("z", 3, "popular"),       # fill
    ]


def test_accept():
    ac = seeded()
    assert ac.followers["i like"] is not ac.followers["like"]    # separate dicts
    assert ac.accept(["i", "like"], "pizza") == 2
    assert ac.followers["i like"]["pizza"] == 2
    assert ac.followers["like"]["pizza"] == 2
    assert ac.accepted["pizza"] == 2                             # once, not twice
    assert ac.words["pizza"] == 20                               # popularity untouched
    assert [w for w, _, _ in ac.next_word(["i", "like"], "", 3)] == ["pasta", "apple", "pizza"]

    assert ac.accept(["like"], "pasta") == 4                     # one-word context
    assert ac.followers["i like"]["pasta"] == 3                  # other level untouched
    assert ac.accepted["pasta"] == 4

    before = (json.dumps(ac.followers, sort_keys=True), dict(ac.accepted))
    assert ac.accept([], "pizza") is None                        # no context: no learning
    assert ac.accept(["i", "like"], "orange") is None            # not in dictionary
    assert (json.dumps(ac.followers, sort_keys=True), dict(ac.accepted)) == before


def test_accept_cold_start():
    ac = Autocomplete()
    ac.set_word("pizza", 1)
    assert ac.accept(["i", "like"], "pizza") == 1
    assert ac.followers == {"i like": {"pizza": 1}, "like": {"pizza": 1}}
    assert ac.accepted == {"pizza": 1}


def test_delete_hides_followers_but_keeps_counts():
    ac = seeded()
    ctx = ["i", "like"]
    ac.delete_word("pizza")
    assert ac.next_word(ctx, "", 5) == [
        ("pasta", 3, "follower"), ("apple", 2, "follower"),
        ("pineapple", 100, "popular"), ("pie", 5, "popular"), ("peach", 3, "popular"),
    ]
    assert ac.accept(ctx, "pizza") is None                       # stale click
    assert ac.followers["i like"]["pizza"] == 1                  # count kept, hidden
    assert ac.accepted["pizza"] == 1

    assert ac.set_word("pizza", 20) is None                      # re-add: new word...
    assert ac.accepted.get("pizza", 0) == 1                      # ...with history
    assert [w for w, _, _ in ac.next_word(ctx, "", 3)] == ["pasta", "apple", "pizza"]


# ----------------------------------------------------------------------
# Part 2: random comparison against the reference
# ----------------------------------------------------------------------

def apply_random_op(rng, ac, ref, ever_used):
    r = rng.random()
    if r < 0.5:
        word, pop = random_word(rng), rng.randint(0, 10)         # few values: many ties
        ever_used.add(word)
        expect(ac.set_word(word, pop), ref.set_word(word, pop), "set_word return value")
        return f"set_word({word!r}, {pop})"
    if r < 0.7:
        if ref.words and rng.random() < 0.7:
            word = rng.choice(sorted(ref.words))
        else:
            word = random_word(rng)                              # often missing
        expect(ac.delete_word(word), ref.delete_word(word), "delete_word return value")
        return f"delete_word({word!r})"
    context = [random_word(rng, 1, 2) for _ in range(rng.randint(0, 3))]
    if ref.words and rng.random() < 0.85:
        word = rng.choice(sorted(ref.words))
    else:
        word = random_word(rng)
    expect(ac.accept(context, word), ref.accept(context, word), "accept return value")
    return f"accept({context!r}, {word!r})"


def run_one_seed(seed, K):
    rng = random.Random(seed)
    ac, ref, ever_used = Autocomplete(k=K), Ref(), set()
    for step in range(1, STEPS + 1):
        op = "(none)"
        try:
            op = apply_random_op(rng, ac, ref, ever_used)
            check_all(ac, ref, K, rng, ever_used)
        except AssertionError as e:
            raise AssertionError(f"K={K} seed={seed} step={step} op={op}\n{e}") from None
    return ac, ref, ever_used


def test_random_oracle():
    # K=3 forces caches to drop words (stale-cache bugs show up fast);
    # K=20 is the real cache size.
    for K in (3, 20):
        for seed in range(1, SEEDS + 1):
            run_one_seed(seed, K)


# ----------------------------------------------------------------------
# Part 3: persistence
# ----------------------------------------------------------------------

def test_save_load_round_trip():
    ac, ref, ever_used = run_one_seed(7, 3)
    path = os.path.join(tempfile.mkdtemp(), "data.json")
    ac.save(path)

    with open(path, encoding="utf-8") as f:
        assert set(json.load(f)) == {"words", "followers", "accepted"}   # no caches saved

    loaded = Autocomplete(k=3)
    assert loaded.load(path) is True
    check_all(loaded, ref, 3, random.Random(1), ever_used)
    for p in ["", "a", "ab", "b", "c"]:
        assert loaded.top_k(p, 3) == ac.top_k(p, 3)


def test_bad_file_falls_back_to_seed():
    cases = {
        "missing file": None,
        "corrupt json": "{not json",
        "wrong shape": '{"words": [], "followers": {}, "accepted": {}}',
        "negative popularity": '{"words": {"a": -1}, "followers": {}, "accepted": {}}',
        "missing key": '{"words": {}}',
    }
    for name, content in cases.items():
        path = os.path.join(tempfile.mkdtemp(), "data.json")
        if content is not None:
            with open(path, "w", encoding="utf-8") as f:
                f.write(content)
        ac = Autocomplete(k=20)
        assert ac.load(path) is False, name
        check_all(ac, seed_ref(), 20, random.Random(1), set(SEED_WORDS))
        if content is not None:
            assert os.path.exists(path + ".bad"), name           # bad file kept
        again = Autocomplete(k=20)                               # seed was written out
        assert again.load(path) is True, name
        expect(again.words, SEED_WORDS, f"{name}: reload")


# ----------------------------------------------------------------------

def main():
    tests = [(n, f) for n, f in globals().items()
             if n.startswith("test_") and callable(f)]
    failed = 0
    for name, fn in tests:
        start = time.time()
        try:
            fn()
        except AssertionError as e:
            failed += 1
            print(f"FAIL  {name}\n{e}\n")
        else:
            print(f"ok    {name}  ({time.time() - start:.1f}s)")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
