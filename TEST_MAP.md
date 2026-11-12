# Test map

All 16 existing oracle tests passed with `python3 -B test_oracle.py`.
Each numbered entry names the exact test in `test_oracle.py`, the cases it covers,
and the implementation to point to. No source logic or seed values were changed.

## The 16 oracle tests

1. `test_seed_prefix_queries`: exact seed words; p/pi/pa prefixes; default query k=1; unknown prefix; fewer matches than requested. Implementation: `trie.py` → `Autocomplete._load_seed`, `Autocomplete.load`, `Autocomplete.top_k`, `_rank_key`.
2. `test_insert_change_overwrite_examples`: insertion, popularity increase/decrease, old-value return, overwriting without duplicates, unchanged follower count after manual update. Implementation: `trie.py` → `Autocomplete.set_word`, `recompute`, `Autocomplete.accept`, `Autocomplete.top_k`.
3. `test_decrease_brings_back_dropped_word`: at K=3, peach drops out, returns after pizza's popularity decreases, then becomes first after its own increase. Implementation: `trie.py` → `Autocomplete.__init__`, `Autocomplete.set_word`, `recompute`.
4. `test_delete`: removes pizza, prunes its unused path, updates pi/p caches, and returns None for repeated or unknown deletions. Implementation: `trie.py` → `Autocomplete.delete_word`, `recompute`, `Autocomplete.top_k`.
5. `test_delete_word_that_is_a_prefix`: app completes itself; deleting app preserves apple; deleting apple prunes the whole branch. Implementation: `trie.py` → `Autocomplete.set_word`, `Autocomplete.delete_word`, `recompute`, `Autocomplete.top_k`.
6. `test_zero_popularity_is_a_real_word`: zero ranks last but remains a stored word; updates and deletion correctly return old zero. Implementation: `trie.py` → `Node.__init__`, `Autocomplete.set_word`, `Autocomplete.delete_word`, `recompute`.
7. `test_ties_are_alphabetical`: equal popularities sort a, b, c regardless of insertion order. Implementation: `trie.py` → `_rank_key`, `recompute`, `Autocomplete.top_k`.
8. `test_next_word_followers_then_fill`: pasta 3, apple 2, pizza 1 precede popular fill, including pineapple 100; partial p filters followers and fill. Implementation: `trie.py` → `Autocomplete.next_word`, `_context_keys`, `_rank_key`, `Autocomplete.top_k`.
9. `test_next_word_backoff`: uses last two context words, backs off to last word, falls back to popularity for unknown context, and supports partial-only input. Implementation: `trie.py` → `_context_keys`, `Autocomplete.next_word`.
10. `test_next_word_levels_are_strict_and_deduplicated`: two-word followers precede one-word followers even with lower counts; words appear once; dictionary fill comes last. Implementation: `trie.py` → `Autocomplete.next_word`, `_context_keys`, `Autocomplete.accept`.
11. `test_accept`: separate follower dictionaries; both context levels increment; accepted total increments once; popularity stays unchanged; one-word context updates only that level; no context and unknown words do not learn. Implementation: `trie.py` → `Autocomplete._load_seed`, `Autocomplete.accept`, `_context_keys`.
12. `test_accept_cold_start`: first acceptance creates both context tables and the accepted total. Implementation: `trie.py` → `Autocomplete.accept`.
13. `test_delete_hides_followers_but_keeps_counts`: deleted words disappear from predictions; stale acceptance is ignored; history survives deletion and returns on re-add. Implementation: `trie.py` → `Autocomplete.delete_word`, `Autocomplete.next_word`, `Autocomplete.accept`, `Autocomplete.set_word`.
14. `test_random_oracle`: 100 seeds × 150 operations at each of K=3 and K=20; compares mutations, return values, all maps, every cache, pruning, prefix queries, and next-word predictions. Test helpers: `test_oracle.py` → `run_one_seed`, `apply_random_op`, `check_all`, `check_structure`, `Ref`, and the `brute_*` functions. Implementation: `trie.py` → `Autocomplete.set_word`, `Autocomplete.delete_word`, `Autocomplete.accept`, `Autocomplete.top_k`, `Autocomplete.next_word`, `recompute`.
15. `test_save_load_round_trip`: persists only words/followers/accepted, reloads at K=3, rebuilds matching caches, and preserves queries. Implementation: `trie.py` → `Autocomplete.save`, `Autocomplete.load`, `Autocomplete._read_file`, `Autocomplete.set_word`.
16. `test_bad_file_falls_back_to_seed`: missing file, corrupt JSON, wrong container type, negative popularity, and missing key; bad existing files survive as `.bad`; seed file reloads successfully. Implementation: `trie.py` → `Autocomplete._read_file` (including local `is_count`), `Autocomplete.load`, `Autocomplete._load_seed`, `Autocomplete.save`.

## Additional checks performed for this request

These checks ran through Flask's real test client with an isolated temporary data
file. They are separate from the 16 oracle tests; the temporary verification script
is `/tmp/autocomplete-client-verify.py`, outside the project.

- Imports, default K=20, exact seed file contents, template location, and Flask-only requirement: `app.py` startup, `trie.py` → `Autocomplete.__init__` / `Autocomplete._load_seed`, `requirements.txt`, `templates/index.html`, `data.json`. Passed using installed Python 3.11.
- Home page returns HTTP 200 and rendered Autocomplete heading: `app.py` → `index`; `templates/index.html`.
- `/api/suggest?prefix=p&k=3` returns pineapple 100, pizza 20, pasta 15: `app.py` → `api_suggest`; `trie.py` → `Autocomplete.top_k`.
- `/api/next` with text `I like ` and k=3 returns pasta 3, apple 2, pizza 1 as followers: `app.py` → `parse_box_text`, `api_next`; `trie.py` → `Autocomplete.next_word`.
- Next-word text `I like p`, k=5 returns pasta, pizza, pineapple, pie, peach: the same parsing and prediction functions.
- Text `I like` without trailing space yields unfinished `like`: `app.py` → `parse_box_text`. This is existing behavior, not an error or code change.
- Reading either suggestion route leaves dictionary popularities, followers, and accepted totals unchanged: `app.py` → `api_suggest`, `api_next`; `trie.py` → `Autocomplete.top_k`, `Autocomplete.next_word`.
- Empty and whitespace top prefixes return “Type to see suggestions”, even with invalid k, and never call `top_k` (verified with a mock that raises if called): `app.py` → early return in `api_suggest`.
- Empty bottom input returns the same note: `app.py` → `api_next`.
- Both query routes reject k values 0, -1, 21, 1.5, abc, and empty string with HTTP 400; accept 1 and 20; omitted k returns one suggestion: `app.py` → `clean_k`, `api_suggest`, `api_next`.
- Accepting pizza after `I like ` increments both follower counts and the accepted total from 1 to 2, leaving all popularities unchanged: `app.py` → `api_accept`, `persist`; `trie.py` → `Autocomplete.accept`, `Autocomplete.save`.
- Acceptance without context reports no learning; unknown orange returns 404: `app.py` → `api_accept`; `trie.py` → `Autocomplete.accept`.
- Manual pizza=20 reports unchanged; adding pea=0 then updating pea=7 reports added/updated; deleting pea succeeds, then returns 404 on repetition: `app.py` → `api_set_word`, `api_delete_word`, `persist`; `trie.py` → `Autocomplete.set_word`, `Autocomplete.delete_word`, `Autocomplete.save`.
- SHA-256 comparisons confirm `trie.py`, `app.py`, `test_oracle.py`, `requirements.txt`, `templates/index.html`, and `data.json` stayed byte-for-byte unchanged.

## Inspection and verification limits

Source inspection confirms `templates/index.html` → `runTop` skips empty requests,
`acceptTop` only fills the top input, and `acceptNext` alone posts learning from
the suggestion UI. `wireList` connects keyboard and mouse acceptance. These
browser interactions were inspected, not exercised in a browser.

A live server was attempted with Werkzeug serving the Flask app, but local port
binding was blocked with “Operation not permitted”. Thus home rendering and route
checks passed in the test client; a live browser/server load is **not confirmed**.
The default Python lacks Flask, and a temporary pip install failed due to PyPI DNS.
The existing Python 3.11 installation includes Flask and passed all app checks.
No code mismatch requiring a fix was found. The trailing-space behavior and the
oracle's use of both K=3 and K=20 are clarifications of the supplied code.
