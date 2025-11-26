# generator.py
import os
import json
import re
from pathlib import Path
from dotenv import load_dotenv
import openai
from typing import List, Dict

# load .env
load_dotenv()
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
if not OPENAI_API_KEY:
    raise RuntimeError("Set OPENAI_API_KEY in a .env file or environment variable.")
openai.api_key = OPENAI_API_KEY

BASE_PROMPTS_DIR = Path(__file__).parent / "prompts"

# Change this to a model you have access to if needed
MODEL_NAME = "gpt-4o-mini"  # replace if you need another model like "gpt-4o" or "gpt-4o-mini"

def load_prompt(name: str) -> str:
    p = BASE_PROMPTS_DIR / name
    if not p.exists():
        raise FileNotFoundError(f"Prompt template not found: {p}")
    return p.read_text(encoding="utf-8")

def call_llm(prompt_text: str, model: str = MODEL_NAME, max_tokens: int = 1200, temperature: float = 0.2) -> str:
    """
    Call the OpenAI ChatCompletion endpoint and return the assistant text.
    """
    # Use ChatCompletion for broader compatibility
    resp = openai.ChatCompletion.create(
        model=model,
        messages=[{"role": "user", "content": prompt_text}],
        max_tokens=max_tokens,
        temperature=temperature,
    )
    # get text
    return resp.choices[0].message.content

def _extract_json_from_text(text: str) -> str:
    """
    Try to extract the first JSON array/object from a text blob.
    """
    # first try to find a JSON array [...]
    array_match = re.search(r'(\[.*\])', text, flags=re.S)
    if array_match:
        return array_match.group(1)
    # then try to find a JSON object {...}
    obj_match = re.search(r'(\{.*\})', text, flags=re.S)
    if obj_match:
        return obj_match.group(1)
    # fallback: raise
    raise ValueError("No JSON array/object found in LLM response.")

def parse_llm_json(raw: str):
    """
    Try parsing the raw LLM response into Python objects.
    This supports a few fallback strategies for slightly malformed JSON.
    """
    # direct attempt
    try:
        return json.loads(raw)
    except Exception:
        pass

    # try to extract a JSON substring then parse
    try:
        snippet = _extract_json_from_text(raw)
        # attempt to fix common issues: replace trailing commas, convert single quotes to double quotes
        snippet_fixed = re.sub(r",\s*]", "]", snippet)
        snippet_fixed = re.sub(r",\s*}", "}", snippet_fixed)
        # only convert single quotes to double quotes when it's safe-ish:
        if "'" in snippet_fixed and '"' not in snippet_fixed[:50]:
            snippet_fixed = snippet_fixed.replace("'", '"')
        return json.loads(snippet_fixed)
    except Exception as e:
        # as a last resort, raise with raw content for debugging
        raise ValueError(f"Failed to parse JSON from LLM response. Error: {e}\nRaw:\n{raw}")

def generate_questions_from_text(source_text: str, qtype: str, n: int, difficulty: str) -> List[Dict]:
    """
    Generate questions from source_text.
    qtype: 'mcq', 'tf', 'full', or 'mixed'
    difficulty: 'easy', 'medium', 'hard', or 'auto'
    """
    source_text = (source_text or "").strip()
    if not source_text:
        return []

    qtype = qtype.lower()
    if qtype == "mixed":
        # split counts
        mcq_n = max(1, n // 2)
        tf_n = max(0, n // 4)
        full_n = max(0, n - mcq_n - tf_n)
        out = []
        if mcq_n > 0:
            out += generate_questions_from_text(source_text, "mcq", mcq_n, difficulty)
        if tf_n > 0:
            out += generate_questions_from_text(source_text, "tf", tf_n, difficulty)
        if full_n > 0:
            out += generate_questions_from_text(source_text, "full", full_n, difficulty)
        # normalize ids
        for i, q in enumerate(out, start=1):
            q["id"] = i
        return out

    template_map = {
        "mcq": "mcq_template.txt",
        "tf": "tf_template.txt",
        "full": "full_template.txt"
    }
    if qtype not in template_map:
        raise ValueError(f"Unknown qtype: {qtype}")

    template = load_prompt(template_map[qtype])
    # format template
    prompt = template.format(source_text=source_text, n=n, difficulty=difficulty)
    raw = call_llm(prompt_text=prompt) if False else call_llm(prompt)  # older signature compat

    parsed = parse_llm_json(raw)
    # ensure list
    if isinstance(parsed, dict):
        parsed = [parsed]
    # add default keys and sanitize
    out = []
    for i, item in enumerate(parsed, start=1):
        try:
            item = dict(item)
        except Exception:
            continue
        item.setdefault("id", i)
        item.setdefault("type", qtype)
        item.setdefault("difficulty", difficulty if difficulty != "auto" else "medium")
        out.append(item)
    return out
