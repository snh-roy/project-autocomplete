# Reading guide

Read the files in this order. Existing source code and seed data were preserved.

## 1. trie.py — the data and algorithms

`DEFAULT_K` is 20. `Autocomplete(k=...)` controls each node's cache capacity;
query `k` controls how many results to return. Seeds are pizza 20, pasta 15,
pie 5, apple 30, pineapple 100, peach 3. Followers for both `i like` and `like`
start as pasta 3, apple 2, pizza 1; accepted totals start with those same counts.

- `Node.__init__`: creates children, an optional word-ending popularity, and a cached result list. `None` means no word; zero is a valid popularity.
- `_rank_key`: sorts numbers descending, then words alphabetically.
- `recompute`: rebuilds one node's best K words from its own word and its children's caches.
- `_context_keys`: chooses the last two finished words, then the last finished word.
- `Autocomplete.__init__`: records K, creates a reentrant lock, and initializes storage.
- `Autocomplete._reset`: clears the trie, dictionary, followers, and accepted totals.
- `Autocomplete.set_word`: inserts or overwrites a manual popularity, then rebuilds caches from the word upward; returns the previous value.
- `Autocomplete.delete_word`: removes the word, prunes unused nodes, and rebuilds caches; keeps learning history for a possible re-add.
- `Autocomplete.top_k`: follows a prefix through the trie and returns up to k cached matches; missing prefixes return an empty list.
- `Autocomplete.next_word`: uses two-word followers first, one-word followers second, then popular dictionary words. Filters by unfinished prefix and removes duplicates. Each follower level ranks by count, then alphabetically.
- `Autocomplete.accept`: increments both applicable follower tables and one accepted total, without changing popularity. Unknown words or no context do nothing.
- `Autocomplete.save`: writes only words, followers, and accepted totals through a temporary file and atomic rename.
- `Autocomplete.load`: reads valid data and rebuilds caches; otherwise preserves a bad file as `.bad`, installs seeds, and saves them.
- `Autocomplete._read_file`: validates JSON structure and nonnegative numeric values. Its local `is_count` helper excludes booleans.
- `Autocomplete._load_seed`: inserts the fixed words and creates separate follower dictionaries so one acceptance cannot increment a shared dictionary twice.

## 2. app.py — input rules and HTTP routes

Startup imports `Autocomplete`, creates a cache with K=20, and loads `data.json`
next to this file (or the path in `AUTOCOMPLETE_DATA`). The UI initially asks
for three results; an API query with omitted k defaults to one.

- `clean_word`: trims, lowercases, and rejects empty, spaced, or over-40-character words.
- `clean_popularity`: accepts nonnegative whole or decimal numbers and limits input length.
- `clean_k`: accepts whole numbers from 1 through 20; returns a specific validation message otherwise.
- `parse_box_text`: separates finished context from the unfinished word, lowercases, and strips edge punctuation. A trailing space or `. , ; : ! ?` finishes the last word.
- `fmt`: displays whole-valued floats without `.0`.
- `reply`: builds the shared JSON response and HTTP status.
- `persist`: saves state; logs a disk error and returns false if saving fails.
- `word_table`: returns dictionary rows alphabetically.
- `no_cache`: adds `Cache-Control: no-store` to API responses.
- `index` (`GET /`): renders `templates/index.html` with UI settings.
- `api_words` (`GET /api/words`): returns the current dictionary table.
- `api_suggest` (`GET /api/suggest`): validates nonempty prefix queries and calls `top_k`. Empty or whitespace input returns exactly “Type to see suggestions” before validation or any trie query.
- `api_next` (`GET /api/next`): parses context, handles empty input, validates k, and calls `next_word`.
- `api_set_word` (`POST /api/word`): adds, updates, or reports an unchanged manual popularity, then saves actual changes.
- `api_delete_word` (`POST /api/word/delete`): deletes and saves, or returns 404 for a missing word.
- `api_accept` (`POST /api/accept`): records a bottom-box acceptance and saves learning; reports no learning without context and rejects deleted words.
- The main guard starts Flask's development server when running `python app.py`.

## 3. templates/index.html — page and browser behavior

This folder is beside `app.py`, where Flask expects it. HTML defines the two
suggestion boxes, manual word form, dictionary table, and status line. CSS styles
them. The JavaScript startup wrapper keeps its variables private.

- `$`: finds a page element by ID. `el`: creates an element with safe text content.
- `setStatus` / `clearStatusFrom`: show messages and clear only messages owned by the relevant operation.
- `api`: sends GET or JSON POST requests and reports network failures.
- `wordLabel`: emphasizes the matched prefix. `makeRow`: builds a suggestion button.
- `showEmpty`: resets a list and displays “Type to see suggestions”. `showNote`: resets a list with another message.
- `highlight`: moves keyboard selection and scrolls it into view.
- `renderTop`: displays prefix matches and their manual popularities.
- `runTop`: returns immediately on empty input; otherwise queries suggestions and ignores responses for older input.
- `acceptTop`: fills the top box and queries again; never sends a learning request.
- `nextTitle`: builds a heading from the parsed context and unfinished prefix.
- `renderNext`: displays follower counts and the separate popular-word fill group.
- `runNext`: handles empty input, queries next words, and ignores outdated responses.
- `replaceUnfinished`: inserts the accepted word, replacing an unfinished token when needed, then adds a space.
- `acceptNext`: posts the bottom-box acceptance, updates the input, and refreshes predictions.
- `wireList`: connects arrow keys, Enter, Tab, Escape, and clicks to selection and acceptance.
- `updateSaveLabel`: chooses “Add” or “Update” based on the typed word.
- `renderTable`: updates the browser's word map and creates dictionary rows and delete buttons.
- `refreshLists`: queries both suggestion boxes after dictionary changes.
- `deleteWord`: posts deletion, updates the table and status, then refreshes suggestions.
- Input listeners call `runTop`, `runNext`, or `updateSaveLabel`. The form submit callback posts a manual popularity. The table click callback deletes a word or fills the edit form. Startup shows both empty notes and loads `/api/words`.

Typing only reads suggestions. Only `acceptNext` posts learning from the UI.
For followers after “I like”, type `I like ` with a trailing space; `I like`
without that space treats `like` as unfinished. This is existing behavior.

## 4. test_oracle.py — independent verification

- `brute_top_k`, `brute_context_keys`, `brute_next_word`: compute expected results directly from dictionaries, independently of trie caches.
- `Ref.__init__`, `Ref.set_word`, `Ref.delete_word`, `Ref.accept`: maintain the simple reference state and expected return values.
- `seed_ref`: builds the reference seed state.
- `expect`: raises an informative error when actual and expected values differ.
- `walk`: visits every trie node. `check_structure`: checks caches, reachable words, and pruning.
- `random_word`, `random_context`: generate reproducible sample inputs.
- `check_all`: compares all maps, every cache, prefix queries, and sampled next-word queries.
- `seeded`: creates an instance loaded from a missing temporary file to exercise seeding.
- The 16 `test_*` functions are explained individually in `TEST_MAP.md`.
- `apply_random_op`: applies the same insert/update, deletion, or acceptance to both models.
- `run_one_seed`: performs 150 operations with comparisons after every step and reports the failing seed and operation if needed.
- `main`: discovers tests, prints results, and exits unsuccessfully if any assertion fails.

The random oracle uses 100 seeds at **each of K=3 and K=20** (30,000 operations).
The dedicated dropped-word regression uses K=3. The oracle imports only `trie.py`;
it does not test Flask or browser interactions.

## 5. requirements.txt, data.json, README.md

`requirements.txt` lists only `Flask`; its installer supplies Flask's dependencies.
`data.json` stores the seed words, follower tables, and accepted totals, not caches.
`README.md` contains the project layout and run/test commands. This guide and
`TEST_MAP.md` are supplementary documents, not application dependencies.

## Verified environment

`python3 -B test_oracle.py`: **16/16 passed**. The default Python lacks Flask;
installed `/opt/homebrew/bin/python3.11` successfully imports and exercises the app.
Installing into a temporary environment failed because PyPI DNS was unavailable.
Live server socket binding returned “Operation not permitted”; Flask's test client
successfully rendered the home page and exercised the routes. No browser execution
was performed. All application checks used temporary data, preserving `data.json`.
