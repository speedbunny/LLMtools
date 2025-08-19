#!/usr/bin/env python3
"""
Open WebUI → Harmony Response Format converter (STATIC PRO VERSION)
Edit CONFIG below, then run: python harmony_convert_static_pro.py
"""

from pathlib import Path
import json, re, csv
from datetime import date

# ============ CONFIG ============
INPUT_PATH = r"/path/to/dir"
OUT_DIR = r"/path/to/dir"
VALIDATE = True
RECURSIVE = True
WRITE_MANIFEST = True
MANIFEST_NAME = "harmony_manifest.csv"
SANITISE_SPECIALS = False
REASONING_OVERRIDES = {
    r"\b5[- ]?thinking(\b|-mini\b)": "high",
    r"\bo3\b": "high",
    r"\bdeepseek[-_]?r1\b": "high",
}
DEFAULT_REASONING = "medium"
# =================================

HARMONY_SYSTEM_TEMPLATE = (
    "<|start|>system<|message|>You are ChatGPT, a large language model trained by OpenAI.\n"
    "Knowledge cutoff: 2024-06\n"
    f"Current date: {date.today().isoformat()}\n\n"
    "Reasoning: {reasoning_level}\n\n"
    "# Valid channels: analysis, commentary, final. Channel must be included for every message.\n"
    "<|end|>\n"
)

SPECIAL_MARKERS = ["<|start|>","<|end|>","<|message|>","<|channel|>","<|constrain|>","<|return|>","<|call|>"]

def sanitise_content(s: str) -> str:
    if not SANITISE_SPECIALS or not isinstance(s, str):
        return s
    repl = {"<|start|>": "‹|start|›","<|end|>": "‹|end|›","<|message|>": "‹|message|›","<|channel|>": "‹|channel|›","<|constrain|>": "‹|constrain|›","<|return|>": "‹|return|›","<|call|>": "‹|call|›"}
    for k, v in repl.items():
        s = s.replace(k, v)
    return s


def validate_walkthrough_str(walkthrough: str) -> list[str]:
    """
    STRICT validator for the single 'harmony_walkthrough' string.

    Priority order for tokenisation:
      1) Use openai_harmony's own encoding (no tiktoken dependency).
      2) Fall back to tiktoken with best-available encoding name
         (o200k_harmony → o200k_base → cl100k_base).
    """
    errs: list[str] = []
    if not isinstance(walkthrough, str) or not walkthrough.strip():
        return ["walkthrough is empty or not a string"]

    token_ids = None
    henc = None
    parser = None

    # ---- Preferred: openai_harmony encoder ----
    try:
        from openai_harmony import load_harmony_encoding, HarmonyEncodingName, StreamableParser, Role
        henc = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS)

        # Try public methods first
        for meth in ("encode", "encode_str", "_encode_str"):
            if hasattr(henc, meth):
                try:
                    token_ids = getattr(henc, meth)(walkthrough)
                    break
                except Exception:
                    token_ids = None
        if token_ids is None:
            raise RuntimeError("openai_harmony encoding present but no working encode method")

        parser = StreamableParser(henc, role=Role.ASSISTANT)
        for t in token_ids:
            parser.process(t)  # raises on spec violations

    except Exception as e_harmony:
        # ---- Fallback: tiktoken ----
        try:
            import tiktoken
            specials = {"<|start|>","<|end|>","<|message|>","<|channel|>","<|constrain|>","<|return|>","<|call|>"}
            enc = None
            for name in ("o200k_harmony", "o200k_base", "cl100k_base"):
                try:
                    enc = tiktoken.get_encoding(name)
                    break
                except Exception:
                    enc = None
            if enc is None:
                return [f"tiktoken encoding unavailable (tried o200k_harmony/o200k_base/cl100k_base); "
                        f"original error from openai_harmony: {e_harmony}"]
            token_ids = enc.encode(walkthrough, allowed_special=specials)

            # Parse using Harmony parser (still required to check spec)
            from openai_harmony import load_harmony_encoding, HarmonyEncodingName, StreamableParser, Role
            henc = load_harmony_encoding(HarmonyEncodingName.HARMONY_GPT_OSS)
            parser = StreamableParser(henc, role=Role.ASSISTANT)
            for t in token_ids:
                parser.process(t)

        except Exception as e_fallback:
            # Distinguish spec violations vs dependency issues
            msg = str(e_fallback)
            if "HarmonyError" in msg:
                return [f"Harmony spec violation: {msg}"]
            if "No module named" in msg or "not installed" in msg:
                return [f"Dependency missing: {msg}"]
            return [f"validator error: {msg}; original harmony error: {e_harmony}"]

    # ---- Extra sanity checks on structure (string-level) ----
    import re as _re
    starts = len(_re.findall(r"<\|start\|>", walkthrough))
    ends = len(_re.findall(r"<\|end\|>", walkthrough))
    if starts != ends:
        errs.append(f"unbalanced blocks: {starts} <|start|> vs {ends} <|end|>")
    m = _re.search(r"<\|start\|>([^<]*)<\|message\|>", walkthrough)
    if not m or not m.group(1).strip().startswith("system"):
        errs.append("first block must be a system message")
    for bad in _re.findall(r"<\|start\|>(user|system|developer)<\|channel\|>", walkthrough):
        errs.append(f"channel marker used with non-assistant role: {bad}")
    return errs


def extract_reasoning_and_final(assistant_markdown: str):
    if not isinstance(assistant_markdown, str):
        return None, ""
    text = assistant_markdown.replace("\r\n", "\n").replace("\r", "\n")
    m = re.search(r"<details[^>]*type=[\"']reasoning[\"'][^>]*>(.*?)</details>\s*", text, flags=re.IGNORECASE|re.DOTALL)
    reasoning = None
    if m:
        inner = m.group(1)
        inner = re.sub(r"<summary>.*?</summary>", "", inner, flags=re.IGNORECASE|re.DOTALL)
        inner = re.sub(r"</?[^>]+>", "", inner)
        inner = re.sub(r"^\s*>\s?", "", inner, flags=re.MULTILINE)
        reasoning = inner.strip()
        final = text[m.end():].strip()
    else:
        final = text.strip()
    return (sanitise_content(reasoning) if reasoning else None), sanitise_content(final)

def compute_reasoning_level(model_names: list[str]) -> str:
    blob = " ".join([str(x) for x in model_names if x is not None])
    for pattern, level in REASONING_OVERRIDES.items():
        try:
            if re.search(pattern, blob, flags=re.IGNORECASE):
                return level
        except re.error:
            pass
    return DEFAULT_REASONING

def build_harmony_from_openwebui(chat: dict) -> dict:
    params = chat.get("params", {}) or {}
    system_dev = params.get("system") or ""
    seed = params.get("seed")
    all_models = []
    if isinstance(chat.get("models"), list):
        all_models += chat["models"]
    for m in chat.get("messages", []):
        if isinstance(m, dict):
            if "model" in m: all_models.append(m["model"])
            if "modelName" in m: all_models.append(m["modelName"])
    reasoning_level = compute_reasoning_level(all_models)
    msgs = list(chat.get("messages") or [])
    msgs.sort(key=lambda m: m.get("timestamp", 0))
    parts = [HARMONY_SYSTEM_TEMPLATE.format(reasoning_level=reasoning_level)]
    if isinstance(system_dev, str) and system_dev.strip():
        parts += ["<|start|>developer<|message|>", sanitise_content(system_dev.strip()), "<|end|>\n"]
    for m in msgs:
        if not isinstance(m, dict):
            continue
        role = m.get("role")
        content = m.get("content", "")
        if not isinstance(content, str) or not content:
            continue
        if role == "user":
            parts += ["<|start|>user<|message|>", sanitise_content(content.strip()), "<|end|>\n"]
        elif role == "assistant":
            reasoning, final = extract_reasoning_and_final(content)
            if reasoning:
                parts += ["<|start|>assistant<|channel|>analysis<|message|>", reasoning, "<|end|>\n"]
            parts += ["<|start|>assistant<|channel|>final<|message|>", final, "<|end|>\n"]
        elif role == "system":
            parts += ["<|start|>developer<|message|>", sanitise_content(content.strip()), "<|end|>\n"]
        else:
            parts += ["<|start|>user<|message|>", sanitise_content(content.strip()), "<|end|>\n"]
    walkthrough = "".join(parts)
    return {"id": chat.get("id", ""),"title": chat.get("title"),"seed": seed,"model_hint": all_models,"harmony_walkthrough": walkthrough,"meta": {"source": "openwebui","created_at": params.get("created_at") or chat.get("createdAt") or chat.get("created_at"),},}

def load_openwebui_container(file_path: Path):
    with open(file_path, "r", encoding="utf-8") as f:
        blob = json.load(f)
    chats = []
    if isinstance(blob, list):
        for entry in blob:
            chat = entry.get("chat") if isinstance(entry, dict) else None
            chat = chat or (entry if isinstance(entry, dict) else None)
            if isinstance(chat, dict):
                chats.append(chat)
    elif isinstance(blob, dict):
        chat = blob.get("chat") or blob
        if isinstance(chat, dict):
            chats.append(chat)
    return chats

def iter_input_files(root: Path, recursive: bool):
    if root.is_file():
        yield root
    else:
        glober = root.rglob if recursive else root.glob
        for p in sorted(glober("*.json")):
            if p.is_file():
                yield p

def convert_static():
    in_path = Path(INPUT_PATH).expanduser()
    out_dir = Path(OUT_DIR).expanduser() if OUT_DIR else (in_path if in_path.is_dir() else in_path.parent)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_rows = []
    manifest_path = out_dir / MANIFEST_NAME if WRITE_MANIFEST else None
    if manifest_path and not manifest_path.exists():
        with open(manifest_path, "w", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerow(["file", "title", "seed", "models", "status", "detail"])
    for fp in iter_input_files(in_path, RECURSIVE):
        status = "SKIP"; detail = ""
        try:
            chats = load_openwebui_container(fp)
            if not chats:
                detail = "no chats found"; print(f"[skip] {fp.name}: {detail}"); continue
            for idx, chat in enumerate(chats):
                out = build_harmony_from_openwebui(chat)
                base = fp.stem; suffix = f"_{idx}" if len(chats) > 1 else ""
                out_fp = out_dir / f"{base}{suffix}.harmony.strict.json"
                with open(out_fp, "w", encoding="utf-8") as f:
                    json.dump(out, f, ensure_ascii=False, indent=2)
                if VALIDATE:
                    errs = validate_walkthrough_str(out.get("harmony_walkthrough", ""))
                    if errs:
                        status, detail = "FAIL", "; ".join(errs); print(f"[FAIL] {out_fp.name}: {detail}")
                    else:
                        status, detail = "PASS", "walkthrough is VALID (openai-harmony parser)"; print(f"[ok] {out_fp.name}: {detail}")
                else:
                    status, detail = "OK", "validation disabled"; print(f"[ok] {out_fp.name}: {detail}")
                if WRITE_MANIFEST:
                    models = " ".join(out.get("model_hint") or [])
                    manifest_rows.append([str(fp), out.get("title"), out.get("seed"), models, status, detail])
        except Exception as e:
            status, detail = "ERROR", str(e); print(f"[error] {fp.name}: {detail}")
            if WRITE_MANIFEST:
                manifest_rows.append([str(fp), "", "", "", status, detail])
    if WRITE_MANIFEST and manifest_rows:
        with open(out_dir / MANIFEST_NAME, "a", newline="", encoding="utf-8") as f:
            w = csv.writer(f); w.writerows(manifest_rows)

if __name__ == "__main__":
    convert_static()
