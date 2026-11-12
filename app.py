"""app.py - Flask app: routes, validation and status messages.

All input cleaning lives here. trie.py assumes clean input and never builds
user-facing text; it returns facts (old value, new count) and this file turns
them into the one-line status messages.

Every route holds ac.lock for the whole operation, including the save, so a
request never sees (or saves) a half-finished update.
"""

import os
import re
import string

from flask import Flask, jsonify, render_template, request

from trie import Autocomplete

MAX_K = 20          # largest k a query may ask for = trie cache size
DEFAULT_UI_K = 3    # the k box starts at this number
DEFAULT_K = 1       # operation-level default when no k is given at all
MAX_WORD_LEN = 40   # keeps a public, shared dictionary from taking huge words

EMPTY_MESSAGE = "Type to see suggestions"
SAVE_WARNING = " (warning: could not save to disk)"

DATA_PATH = os.environ.get("AUTOCOMPLETE_DATA") or os.path.join(
    os.path.dirname(os.path.abspath(__file__)), "data.json")

app = Flask(__name__)
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024    # requests are tiny

ac = Autocomplete(k=MAX_K)
ac.load(DATA_PATH)      # data file, or seed data if it is missing/unreadable


# ----------------------------------------------------------------------
# validation: each returns (clean_value, error_message); error is None if fine
# ----------------------------------------------------------------------

def clean_word(raw):
    """Trim, lowercase, and check a dictionary word."""
    word = ("" if raw is None else str(raw)).strip().lower()
    if not word:
        return None, "Enter a word."
    if any(ch.isspace() for ch in word):
        return None, "A word can't contain spaces."
    if len(word) > MAX_WORD_LEN:
        return None, f"A word can be at most {MAX_WORD_LEN} characters."
    return word, None


def clean_popularity(raw):
    """A number >= 0 (whole or decimal). Returns an int when it is whole."""
    text = ("" if raw is None else str(raw)).strip()
    if not text:
        return None, "Enter a popularity."
    if re.fullmatch(r"-\d+(\.\d+)?", text):
        return None, "Popularity must be 0 or more."
    if not re.fullmatch(r"\d+(\.\d+)?", text):
        return None, "Popularity must be a number."
    if len(text) > 15:
        return None, "Popularity is too large."
    value = float(text)
    return (int(value) if value.is_integer() else value), None


def clean_k(raw):
    """k must be a whole number from 1 to MAX_K. No k at all means top 1."""
    if raw is None:
        return DEFAULT_K, None
    text = str(raw).strip()
    if re.fullmatch(r"[+-]?\d+", text):
        try:
            k = int(text)
        except ValueError:                       # absurdly long digit strings
            return None, f"k can be at most {MAX_K}"
        if k <= 0:
            return None, "k must be at least 1."
        if k > MAX_K:
            return None, f"k can be at most {MAX_K}"
        return k, None
    if re.fullmatch(r"[+-]?(\d+\.\d*|\.\d+)", text):
        return None, "k must be a whole number."
    return None, "k must be a number."


def parse_box_text(text):
    """Split the next-word box into (finished context words, unfinished word).

    A trailing space, or a trailing . , ; : ! ? finishes the last word.
    Punctuation is stripped from the edges of each word; inner apostrophes
    stay ("don't").
    """
    s = text.lower()
    stripped = [t.strip(string.punctuation) for t in s.split()]
    finished = bool(s) and (s[-1].isspace() or s[-1] in ".,;:!?")
    if not finished and stripped and stripped[-1]:
        return [t for t in stripped[:-1] if t], stripped[-1]
    return [t for t in stripped if t], ""


# ----------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------

def fmt(n):
    """Show 10.0 as 10, leave other numbers alone."""
    if isinstance(n, float) and n.is_integer():
        return str(int(n))
    return str(n)


def reply(ok, message, status=200, **extra):
    body = {"ok": ok, "message": message}
    body.update(extra)
    return jsonify(body), status


def persist():
    """Save to disk; False if the write failed (the change stays in memory)."""
    try:
        ac.save(DATA_PATH)
        return True
    except OSError:
        app.logger.exception("could not save %s", DATA_PATH)
        return False


def word_table():
    """Dictionary rows, alphabetical, read from the flat map (not the trie)."""
    return [{"word": w, "popularity": p} for w, p in sorted(ac.words.items())]


@app.after_request
def no_cache(response):
    if request.path.startswith("/api/"):
        response.headers["Cache-Control"] = "no-store"
    return response


# ----------------------------------------------------------------------
# routes
# ----------------------------------------------------------------------

@app.route("/")
def index():
    return render_template("index.html", max_k=MAX_K, default_k=DEFAULT_UI_K)


@app.route("/api/words")
def api_words():
    with ac.lock:
        return reply(True, None, words=word_table())


@app.route("/api/suggest")
def api_suggest():
    """Top box: prefix completion. `seq` is echoed so the page can ignore
    a late reply for an older keystroke."""
    seq = request.args.get("seq")
    prefix = request.args.get("prefix", "").strip().lower()

    if not prefix:                  # empty box: no query, never top_k("")
        return reply(True, EMPTY_MESSAGE, seq=seq, suggestions=[])

    k, error = clean_k(request.args.get("k"))
    if error:
        return reply(False, error, 400, seq=seq, suggestions=[])

    with ac.lock:
        found = ac.top_k(prefix, k)
    suggestions = [{"word": w, "popularity": p} for w, p in found]
    message = None if suggestions else f"no suggestions for '{prefix}'"
    return reply(True, message, seq=seq, suggestions=suggestions)


@app.route("/api/next")
def api_next():
    """Bottom box: followers first, then dictionary fill."""
    seq = request.args.get("seq")
    context, partial = parse_box_text(request.args.get("text", ""))

    if not context and not partial:         # empty box: no query
        return reply(True, EMPTY_MESSAGE, seq=seq, suggestions=[],
                     context=[], partial="")

    k, error = clean_k(request.args.get("k"))
    if error:
        return reply(False, error, 400, seq=seq, suggestions=[],
                     context=context, partial=partial)

    with ac.lock:
        found = ac.next_word(context, partial, k)
    suggestions = [{"word": w, "number": n, "source": src} for w, n, src in found]
    message = None if suggestions else (
        f"no suggestions for '{request.args.get('text', '').strip()}'")
    return reply(True, message, seq=seq, suggestions=suggestions,
                 context=context, partial=partial)


@app.route("/api/word", methods=["POST"])
def api_set_word():
    """Add a new word or overwrite an existing popularity (one form, one call)."""
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}

    word, error = clean_word(data.get("word"))
    if error:
        return reply(False, error, 400)
    popularity, error = clean_popularity(data.get("popularity"))
    if error:
        return reply(False, error, 400)

    with ac.lock:
        old = ac.words.get(word)
        if old is not None and old == popularity:
            return reply(True, f"{word} already {fmt(old)}, no change",
                         action="unchanged", words=word_table())

        ac.set_word(word, popularity)
        saved = persist()

        if old is None:
            message = f"added {word} ({fmt(popularity)})"
            history = ac.accepted.get(word, 0)
            if history > 0:
                message += (f"; follow history restored "
                            f"({history} accept{'s' if history != 1 else ''})")
            action = "added"
        else:
            message = f"updated {word} from {fmt(old)} to {fmt(popularity)}"
            action = "updated"
        table = word_table()

    return reply(True, message + ("" if saved else SAVE_WARNING),
                 action=action, words=table)


@app.route("/api/word/delete", methods=["POST"])
def api_delete_word():
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}

    word, error = clean_word(data.get("word"))
    if error:
        return reply(False, error, 400)

    with ac.lock:
        old = ac.delete_word(word)
        if old is None:
            return reply(False, "word not found", 404, words=word_table())
        saved = persist()
        table = word_table()

    return reply(True, f"deleted {word}" + ("" if saved else SAVE_WARNING),
                 words=table)


@app.route("/api/accept", methods=["POST"])
def api_accept():
    """Bottom box only: the user accepted a suggestion. The top box never
    learns; it just fills its input on the page."""
    data = request.get_json(silent=True)
    data = data if isinstance(data, dict) else {}

    word, error = clean_word(data.get("word"))
    if error:
        return reply(False, error, 400)
    context, _ = parse_box_text(str(data.get("text", "")))

    with ac.lock:
        if word not in ac.words:                    # deleted since the query
            return reply(False, "word not found", 404, learned=False)
        count = ac.accept(context, word)
        if count is None:                           # no words before it
            return reply(True, f"{word}: no earlier words, nothing learned",
                         learned=False)
        saved = persist()

    key = " ".join(context[-2:])
    message = f"learned '{word}' after '{key}' ({count} time{'s' if count != 1 else ''})"
    return reply(True, message + ("" if saved else SAVE_WARNING),
                 learned=True, count=count)


if __name__ == "__main__":
    app.run(debug=True)
