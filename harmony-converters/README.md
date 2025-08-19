Convert **Open WebUI** chat export JSON files into **Harmony Response Format** — with strict validation, recursive folder processing, a manifest CSV, optional sanitisation of Harmony markers inside message text, and reasoning-level overrides.

This is a **single-file**, edit-the-CONFIG-block script. No flags required.

---

## Requirements

* Python **3.9+**
* For strict validation (recommended):

  * `openai-harmony` (required)
  * `tiktoken` (optional fallback)

Install:

```bash
pip install openai-harmony tiktoken
```

> Validation will still run if `tiktoken` is missing; the script prefers the `openai_harmony` encoder and only falls back to `tiktoken` if needed.

---

## Quick start

1. Open the script and edit the **CONFIG** block at the top:

```python
# ============ CONFIG ============
INPUT_PATH = r"/abs/path/to/folder/or/file.json"
OUT_DIR = None                 # None => alongside the inputs / inside the folder
VALIDATE = True                # strict: Harmony parser on 'harmony_walkthrough'
RECURSIVE = True               # include subfolders when INPUT_PATH is a folder

WRITE_MANIFEST = True
MANIFEST_NAME = "harmony_manifest.csv"

SANITISE_SPECIALS = False      # neutralise Harmony markers in *message content* only

REASONING_OVERRIDES = {        # regex -> "low"/"medium"/"high"
    r"\b5[- ]?thinking(\b|-mini\b)": "high",
    r"\bo3\b": "high",
    r"\bdeepseek[-_]?r1\b": "high",
}
DEFAULT_REASONING = "medium"
# =================================
```

2. Run it:

```bash
python harmony_convert_static_pro.py
```

Outputs are written as one JSON per input:

```
<basename>.harmony.strict.json
```

---

## What it does

* **Adds Harmony system header** with knowledge cutoff, current date, and `Reasoning: <level>`.
* **Maps WebUI “system”** → Harmony **developer** message (so your app’s rules are preserved).
* **Splits assistant messages**:

  * `<details type="reasoning">…</details>` → `assistant|analysis`
  * everything after that → `assistant|final`
* **Sorts** all messages by `timestamp`.
* **(Optional)** Sanitises Harmony special markers found *inside message content* to avoid accidental markup (e.g. `<|start|>` → `‹|start|›`).

---

## Strict validation (what “VALIDATE=True” does)

When `VALIDATE=True`, the script verifies the **single** `harmony_walkthrough` string in each output using the **official Harmony parser**:

1. **Tokenisation**: tries `openai_harmony`’s encoder first; if unavailable, falls back to `tiktoken` (`o200k_harmony` → `o200k_base` → `cl100k_base`).
2. **Parsing**: feeds tokens to `openai_harmony.StreamableParser`.

   * If Harmony would reject it, you’ll see `[FAIL] … Harmony spec violation: …`
   * Otherwise you’ll see `[ok] … walkthrough is VALID (openai-harmony parser)`
3. **Extra checks**: balanced `<|start|>`/`<|end|>`, first block must be `system`, and `<|channel|>` only appears with `assistant`.

---

## Configuration options (in detail)

* **`INPUT_PATH`**:
  Path to a single WebUI JSON export or a folder containing many.

  * File ⇒ converts just that file.
  * Folder ⇒ converts all `*.json` (recursively if `RECURSIVE=True`).

* **`OUT_DIR`**:
  Where to place outputs.

  * `None` ⇒ alongside inputs (for a file) or **inside** the folder you pointed at.

* **`VALIDATE`** (bool):
  Enable strict Harmony validation via `openai_harmony` (recommended). See “Strict validation” above.

* **`RECURSIVE`** (bool):
  Process subdirectories when `INPUT_PATH` is a folder.

* **`WRITE_MANIFEST`** (bool) & **`MANIFEST_NAME`** (str):
  Write a CSV summary in `OUT_DIR`. The CSV includes:

  ```
  file,title,seed,models,status,detail
  ```

  * `status` ∈ {`PASS`,`FAIL`,`OK`,`ERROR`}
  * `detail` carries the parser message (for `FAIL`) or “validation disabled”.

* **`SANITISE_SPECIALS`** (bool):
  If `True`, the script **only** changes Harmony markers inside message bodies:
  `<|start|>` → `‹|start|›`, `<|end|>` → `‹|end|›`, etc.
  Use this if your chat content sometimes contains literal Harmony tokens that might confuse the parser during replay. (Sanitisation does **not** touch the Harmony control blocks the script emits.)

* **`REASONING_OVERRIDES`** (dict\[str, str]):
  Regex → reasoning level mapping. The script concatenates all model names it finds and applies these patterns in order. Allowed levels: `"low"`, `"medium"`, `"high"`.
  Example entries included:

  * `5[- ]?thinking(-mini)?`, `o3`, `deepseek[-_]?r1` ⇒ `"high"`

* **`DEFAULT_REASONING`** (str):
  Fallback level if no override matches. Typically `"medium"`.

> **Windows paths**: prefer raw strings `r"C:\path\to\folder"` to avoid backslash escapes.

---

## Example runs

**1) Basic convert with validation:**

```python
# CONFIG
INPUT_PATH = r"/data/webui-dumps"
OUT_DIR    = r"/data/converted"
VALIDATE   = True
RECURSIVE  = True
```

Run:

```bash
python harmony_convert_static_pro.py
```

Output (example):

```
[ok] seed23-judged.harmony.strict.json: walkthrough is VALID (openai-harmony parser)
[ok] seed123-judged.harmony.strict.json: walkthrough is VALID (openai-harmony parser)
```

Manifest (CSV):

```csv
file,title,seed,models,status,detail
/data/webui-dumps/seed23-judged.json,Seed 23,42,"gpt-5-thinking-mini",PASS,walkthrough is VALID (openai-harmony parser)
```

**2) Sanitise specials (rare edge cases):**

```python
SANITISE_SPECIALS = True
```

Use this if your transcripts include literal strings like `<|start|>` inside user/assistant text and you want to neutralise them.

---

## Output format

Each output file is a JSON blob:

```json
{
  "id": "…",
  "title": "…",
  "seed": 123,
  "model_hint": ["gpt-5-thinking-mini"],
  "harmony_walkthrough": "<|start|>system<|message|>…<|end|>\n<|start|>user<|message|>…",
  "meta": {"source": "openwebui", "created_at": "…"}
}
```

---

## Troubleshooting

* **`Harmony spec violation`**
  Your walkthrough truly breaks the spec (e.g., channel on a non-assistant role). The message tells you where/why.

* **`openai-harmony not installed` / `Dependency missing`**
  Install validation extras:

  ```bash
  pip install openai-harmony tiktoken
  ```

* **`tiktoken/o200k_harmony unavailable`**
  Not a blocker. The script prefers the `openai_harmony` encoder and will fall back to another `tiktoken` encoding if needed.

* **Empty or odd WebUI export**
  Some exports are arrays with `{ "chat": … }` items; others are a single `chat` object. The script handles both. If it prints `[skip] … no chats found`, the file likely isn’t a WebUI export.

---

## Safety & privacy

* No network calls. Everything runs locally.
* The script only surfaces reasoning that already exists in your export (inside `<details type="reasoning">…</details>`).

---

## Licence

CC0 — do what you like, but no warranty.
