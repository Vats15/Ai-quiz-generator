# generator.py


import os
import json
import re
from pathlib import Path

import openai

# choose model by env var or default
MODEL_NAME = os.environ.get("MODEL_NAME", "gpt-4o-mini")  # change if you want another model
openai.api_key = os.getenv("OPENAI_API_KEY")
if not openai.api_key:
    raise RuntimeError("Set OPENAI_API_KEY in a .env file or environment variable.")

BASE_PROMPTS_DIR = Path(__file__).parent / "prompts"


def _read_prompt_file(name: str) -> str | None:
    p = BASE_PROMPTS_DIR / name
    if p.exists():
        return p.read_text(encoding="utf-8")
    return None


# fallback prompt — structured output as JSON array
FALLBACK_PROMPTS = {
    "mcq": (
        "You are an exam creator. Given the following source text delimited by triple backticks, "
        "create {n} multiple-choice questions (MCQs). RETURN ONLY A JSON ARRAY. "
        "Each element must be an object with keys: id (int, optional), type ('mcq'), question (string), "
        "options (list of 4 strings), answer (one of 'A','B','C','D'), explanation (short string, optional), "
        "difficulty ('easy','medium','hard').\n\n"
        "Source text:\n```{source_text}```\n\nReturn the JSON array only."
    ),
    "tf": (
        "You are an exam creator. Given the following source text delimited by triple backticks, "
        "create {n} True/False questions. RETURN ONLY A JSON ARRAY, where each object has keys: "
        "id (int, optional), type ('tf'), question (string), answer (true/false), explanation (optional), difficulty.\n\n"
        "Source text:\n```{source_text}```\n\nReturn the JSON array only."
    ),
    "full": (
        "You are an exam creator. Given the following source text delimited by triple backticks, create {n} "
        "short-answer questions. RETURN ONLY A JSON ARRAY where each object has keys: "
        "id (int, optional), type ('full'), question (string), answer (string), explanation (optional), difficulty.\n\n"
        "Source text:\n```{source_text}```\n\nReturn the JSON array only."
    ),
}


def _extract_json_from_text(text: str) -> str:
    """
    Try to extract the first JSON array or object from the text.
    If the model returned a string with commentary + JSON, we extract the JSON substring.
    """
    # common approach: find the first '[' and matching closing ']' OR first '{'...' }' if array not found
    # but prefer top-level array
    text = text.strip()
    # try to find first JSON array
    array_start = text.find('[')
    if array_start != -1:
        # attempt to find matching bracket by counting
        depth = 0
        for i in range(array_start, len(text)):
            if text[i] == '[':
                depth += 1
            elif text[i] == ']':
                depth -= 1
                if depth == 0:
                    return text[array_start:i+1]
    # fallback: try to find JSON object sequence like { ... } repeated
    obj_start = text.find('{')
    if obj_start != -1:
        # try to find closing bracket for last top-level object sequence
        depth = 0
        for i in range(obj_start, len(text)):
            if text[i] == '{':
                depth += 1
            elif text[i] == '}':
                depth -= 1
                if depth == 0:
                    candidate = text[obj_start:i+1]
                    # if there's a sequence of objects separated by commas, wrap in [ ... ]
                    # quick heuristic: if after candidate there's a comma+{ then collect more
                    j = i+1
                    objs = [candidate]
                    while True:
                        # skip whitespace
                        while j < len(text) and text[j].isspace():
                            j += 1
                        if j < len(text) and text[j] == ',':
                            # find next object
                            j += 1
                            while j < len(text) and text[j].isspace():
                                j += 1
                            if j < len(text) and text[j] == '{':
                                # find end of next object
                                k = j
                                depth2 = 0
                                for k in range(j, len(text)):
                                    if text[k] == '{':
                                        depth2 += 1
                                    elif text[k] == '}':
                                        depth2 -= 1
                                        if depth2 == 0:
                                            objs.append(text[j:k+1])
                                            j = k+1
                                            break
                                continue
                        break
                    if len(objs) > 1:
                        return "[" + ",".join(objs) + "]"
                    return candidate
    # last-resort: try regex to find {...} or [...]
    m = re.search(r'(\[.*\])', text, flags=re.S)
    if m:
        return m.group(1)
    m2 = re.search(r'(\{.*\})', text, flags=re.S)
    if m2:
        return m2.group(1)
    # nothing found
    return text


def _safe_json_load(s: str):
    """
    Try json.loads; if it fails try to replace smart quotes or trailing commas and try again.
    """
    try:
        return json.loads(s)
    except Exception:
        # quick repairs
        s2 = s.replace("“", '"').replace("”", '"').replace("’", "'")
        # remove trailing commas before closing brackets/braces
        s2 = re.sub(r',\s*([\]\}])', r'\1', s2)
        try:
            return json.loads(s2)
        except Exception:
            # give up gracefully
            raise


def _normalize_questions(raw_list, requested_type: str) -> list:
    """
    Ensure each element is a dict with required keys and assign missing ids sequentially.
    """
    out = []
    for item in raw_list:
        if not isinstance(item, dict):
            continue
        q = dict(item)  # copy
        # ensure type
        if "type" not in q:
            q["type"] = requested_type if requested_type in ("mcq", "tf", "full", "mixed") else "mcq"
        # ensure question text
        q.setdefault("question", q.get("question", "").strip() if q.get("question") else "")
        # ensure difficulty
        q.setdefault("difficulty", q.get("difficulty", "medium"))
        # ensure options/answer presence for mcq
        if q["type"] == "mcq":
            opts = q.get("options") or []
            # if options is a string, try splitting lines
            if isinstance(opts, str):
                opts = [o.strip() for o in opts.splitlines() if o.strip()]
            # make sure options list length is at least 2
            if not isinstance(opts, list):
                opts = []
            # pad with placeholders if less than 4
            while len(opts) < 4:
                opts.append(f"Option {len(opts)+1}")
            q["options"] = opts[:4]
            if "answer" not in q or q["answer"] is None:
                # default answer is A
                q["answer"] = "A"
        if q["type"] == "tf":
            # ensure boolean answer
            a = q.get("answer", True)
            if isinstance(a, str):
                a_lower = a.strip().lower()
                q["answer"] = True if a_lower in ("true", "t", "yes") else False
            else:
                q["answer"] = bool(a)
        # explanation is optional
        q.setdefault("explanation", q.get("explanation", ""))
        out.append(q)
    # assign ids if missing
    next_id = 1
    for item in out:
        if "id" not in item or not isinstance(item.get("id"), int):
            item["id"] = next_id
            next_id += 1
        else:
            # keep numeric id but ensure next_id is after it
            try:
                if item["id"] >= next_id:
                    next_id = item["id"] + 1
            except Exception:
                pass
    return out


def generate_questions_from_text(source_text: str, qtype: str = "mcq", n: int = 5, difficulty: str = "medium") -> list:
    """
    Main entrypoint used by app.py.
    Returns a list of question dicts.
    """
    # read a template if present
    template_file = f"{qtype}_template.txt"
    prompt_template = _read_prompt_file(template_file) or FALLBACK_PROMPTS.get(qtype, FALLBACK_PROMPTS["mcq"])

    prompt = prompt_template.format(source_text=source_text, n=n, difficulty=difficulty)

    # Call OpenAI ChatCompletion (or completions) - prefer chat API
    try:
        resp = openai.ChatCompletion.create(
            model=os.environ.get("MODEL_NAME", MODEL_NAME),
            messages=[
                {"role": "system", "content": "You are an assistant that outputs clean JSON and nothing else."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=2000,
            temperature=0.2,
        )
    except Exception as e:
        raise RuntimeError(f"LLM request failed: {e}")

    # extract text
    try:
        llm_text = resp["choices"][0]["message"]["content"]
    except Exception:
        # fallback for older OpenAI libs or other shapes
        try:
            llm_text = resp["choices"][0]["text"]
        except Exception as e:
            raise RuntimeError(f"Could not read model response: {e}")

    # Extract likely JSON
    json_text = _extract_json_from_text(llm_text)
    try:
        parsed = _safe_json_load(json_text)
    except Exception as e:
        # as a last resort, if json not parseable, raise a helpful error including model text
        raise RuntimeError(f"Failed to parse JSON from model response. Raw output:\n{llm_text}\n\nParse error: {e}")

    # If parsed is a dict (single object), wrap in list
    if isinstance(parsed, dict):
        parsed = [parsed]
    if not isinstance(parsed, list):
        raise RuntimeError("Model output was not a JSON array of questions.")

    # Normalize and ensure ids
    questions = _normalize_questions(parsed, requested_type=qtype)

    # If the model returned fewer items than requested, that's okay — return what we have
    return questions
