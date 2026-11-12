"""trie.py - autocomplete data structures and logic.

Holds the trie, the flat word -> popularity map, the next-word follower
tables, and JSON persistence. It assumes clean input (lowercase words with no
spaces, popularity >= 0, valid k). All validation lives in app.py.
"""

import json
import os
import threading

DEFAULT_K = 20  # default cache size = largest k a query may ask for

SEED_WORDS = [
    ("pizza", 20),
    ("pasta", 15),
    ("pie", 5),
    ("apple", 30),
    ("pineapple", 100),
    ("peach", 3),
]
SEED_FOLLOWERS = {"pasta": 3, "apple": 2, "pizza": 1}  # after "I like"


class Node:
    """One trie node.

    children   : char -> Node
    popularity : number, or None when no word ends here (0 is a real word)
    top        : up to K (word, popularity) pairs for this node's subtree,
                 sorted by popularity descending, then word ascending
    """

    __slots__ = ("children", "popularity", "top")

    def __init__(self):
        self.children = {}
        self.popularity = None
        self.top = []


def _rank_key(entry):
    """Sort key for (word, popularity): popularity descending, word ascending."""
    return (-entry[1], entry[0])


def recompute(node, prefix, k):
    """Rebuild node.top from the node's own word plus its children's caches.

    This is the only place a `top` list is ever written. Children must
    already be correct, so callers go from the deepest node up to the root.
    """
    candidates = []
    if node.popularity is not None:
        candidates.append((prefix, node.popularity))
    for child in node.children.values():
        candidates.extend(child.top)
    candidates.sort(key=_rank_key)
    node.top = candidates[:k]


def _context_keys(context_words):
    """Follower-table keys for a list of finished words, longest first."""
    keys = []
    if len(context_words) >= 2:
        keys.append(" ".join(context_words[-2:]))
    if len(context_words) >= 1:
        keys.append(context_words[-1])
    return keys


class Autocomplete:
    """Trie + flat map + follower tables, kept in sync by one set of methods."""

    def __init__(self, k=DEFAULT_K):
        self.K = k  # cache size per node (not the per-query k)
        # RLock: app.py wraps whole operations in `with ac.lock:`, and save()
        # takes the same lock again from inside them.
        self.lock = threading.RLock()
        self._reset()

    def _reset(self):
        self.root = Node()
        self.words = {}      # word -> popularity (the flat map)
        self.followers = {}  # context -> {word -> follow count}
        self.accepted = {}   # word -> total times accepted

    # ------------------------------------------------------------------
    # writes: insert / update / delete
    # ------------------------------------------------------------------

    def set_word(self, word, popularity):
        """Insert a new word or overwrite an existing one.

        Returns the old popularity, or None if the word is new.
        """
        old = self.words.get(word)

        # 1. walk down, creating missing nodes, remembering the path
        path = [(self.root, "")]
        node = self.root
        prefix = ""
        for ch in word:
            if ch not in node.children:
                node.children[ch] = Node()
            node = node.children[ch]
            prefix += ch
            path.append((node, prefix))

        # 2. write the value in both structures
        node.popularity = popularity
        self.words[word] = popularity

        # 3. rebuild caches, deepest node first
        for n, p in reversed(path):
            recompute(n, p, self.K)

        return old

    def delete_word(self, word):
        """Delete a word. Returns its old popularity, or None if not found.

        Follower counts and `accepted` are kept on purpose; next_word()
        hides followers that are not in the dictionary.
        """
        old = self.words.get(word)
        if old is None:
            return None

        # 1. walk down; every node on this word's path exists
        path = [(self.root, "")]
        node = self.root
        prefix = ""
        for ch in word:
            node = node.children[ch]
            prefix += ch
            path.append((node, prefix))

        # 2. remove the word
        node.popularity = None
        del self.words[word]

        # 3. deepest first: prune empty nodes, recompute the rest
        for i in range(len(path) - 1, -1, -1):
            n, p = path[i]
            if i > 0 and n.popularity is None and not n.children:
                parent = path[i - 1][0]
                del parent.children[word[i - 1]]
            else:
                recompute(n, p, self.K)

        return old

    # ------------------------------------------------------------------
    # reads
    # ------------------------------------------------------------------

    def top_k(self, prefix, k=1):
        """Top k (word, popularity) pairs starting with prefix, ranked."""
        node = self.root
        for ch in prefix:
            node = node.children.get(ch)
            if node is None:
                return []
        return node.top[:k]

    def next_word(self, context_words, partial="", k=1):
        """Next-word suggestions: followers first, then dictionary fill.

        context_words : finished lowercase words before the cursor (may be [])
        partial       : unfinished last word, "" if the box ends in a space
        Returns a list of (word, number, source) where source is "follower"
        (number = follow count) or "popular" (number = popularity).
        """
        result = []
        seen = set()

        # levels 1 and 2: followers of the last two words, then the last one
        for key in _context_keys(context_words):
            table = self.followers.get(key, {})
            level = [
                (w, c)
                for w, c in table.items()
                if w in self.words and w.startswith(partial) and w not in seen
            ]
            level.sort(key=_rank_key)
            for w, c in level:
                result.append((w, c, "follower"))
                seen.add(w)

        # level 3: dictionary fill, already sorted by the trie's cache
        for w, pop in self.top_k(partial, self.K):
            if w not in seen:
                result.append((w, pop, "popular"))

        return result[:k]

    # ------------------------------------------------------------------
    # learning
    # ------------------------------------------------------------------

    def accept(self, context_words, word):
        """Record that the user accepted `word` after `context_words`.

        Returns the new follow count at the longest context, or None when the
        word is not in the dictionary or there is no context to learn from.
        Only followers and accepted change; the dictionary and trie do not.
        """
        if word not in self.words:
            return None

        keys = _context_keys(context_words)
        if not keys:
            return None

        for key in keys:
            table = self.followers.setdefault(key, {})
            table[word] = table.get(word, 0) + 1

        self.accepted[word] = self.accepted.get(word, 0) + 1  # once per accept
        return self.followers[keys[0]][word]

    # ------------------------------------------------------------------
    # persistence
    # ------------------------------------------------------------------

    def save(self, path):
        """Write words, followers and accepted atomically (temp file + rename)."""
        data = {
            "words": self.words,
            "followers": self.followers,
            "accepted": self.accepted,
        }
        tmp = path + ".tmp"
        with self.lock:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, path)

    def load(self, path):
        """Load from path, rebuilding the trie through set_word().

        If the file is missing, unreadable or the wrong shape, load the seed
        data instead and write it out (an unreadable file is kept as
        path + ".bad"). Returns True if the file was used, False for seed.
        """
        with self.lock:
            data = self._read_file(path)
            if data is None:
                if os.path.exists(path):
                    try:
                        os.replace(path, path + ".bad")
                    except OSError:
                        pass
                self._load_seed()
                self.save(path)
                return False

            self._reset()
            self.followers = data["followers"]
            self.accepted = data["accepted"]
            for word, pop in data["words"].items():
                self.set_word(word, pop)
            return True

    @staticmethod
    def _read_file(path):
        """Parsed file contents, or None if missing, unreadable or malformed."""
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return None

        def is_count(x):
            return isinstance(x, (int, float)) and not isinstance(x, bool) and x >= 0

        try:
            if not isinstance(data, dict):
                return None
            words = data["words"]
            followers = data["followers"]
            accepted = data["accepted"]
            if not (isinstance(words, dict) and isinstance(followers, dict)
                    and isinstance(accepted, dict)):
                return None
            if not all(isinstance(w, str) and w and is_count(p)
                       for w, p in words.items()):
                return None
            for ctx, table in followers.items():
                if not (isinstance(ctx, str) and isinstance(table, dict)):
                    return None
                if not all(isinstance(w, str) and is_count(c)
                           for w, c in table.items()):
                    return None
            if not all(isinstance(w, str) and is_count(c)
                       for w, c in accepted.items()):
                return None
        except KeyError:
            return None
        return data

    def _load_seed(self):
        self._reset()
        for word, pop in SEED_WORDS:
            self.set_word(word, pop)
        # separate dict objects per context, so one accept can't hit both
        self.followers["i like"] = dict(SEED_FOLLOWERS)
        self.followers["like"] = dict(SEED_FOLLOWERS)
        self.accepted = dict(SEED_FOLLOWERS)
