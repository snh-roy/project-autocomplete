# Project Autocomplete

A Flask autocomplete app backed by a trie, with popularity-ranked suggestions,
next-word predictions, and JSON persistence created by AI, driven by a human. 

## Project structure

```text
project-autocomplete/
  trie.py
  app.py
  test_oracle.py
  requirements.txt
  templates/
    index.html
  data.json
  README.md
```

## Run

Install dependencies and start the app with Python 3:

```sh
python3 -m pip install -r requirements.txt
python3 app.py
```

Open http://127.0.0.1:5000 in your browser.

`data.json` stores dictionary words, follower counts, and accepted suggestions.
Changes are saved automatically. Set `AUTOCOMPLETE_DATA` to use another data file.

## Test

```sh
python3 test_oracle.py
```

The oracle compares the trie against a brute-force reference and checks JSON
save/load behavior. It uses only the Python standard library.
