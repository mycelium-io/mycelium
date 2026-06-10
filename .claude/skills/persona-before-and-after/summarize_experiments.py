#!/usr/bin/env python3
"""
summarize_experiments.py — Aggregate persona-before-and-after gist results.

Usage:
    python3 summarize_experiments.py gists.txt
    python3 summarize_experiments.py https://gist.github.com/... https://gist.github.com/...
    python3 summarize_experiments.py --output summary.md gists.txt

For each gist it:
  1. Fetches evaluation.md + session transcripts via the GitHub Gist API.
  2. Parses the Summary table to extract per-experiment metrics.
  3. Extracts the issues/options that were actually surfaced in both the
     before (free-chat) and after (Mycelium) runs.
  4. Maps the scenario to the ground truth in mycelium-io/agent-personas repo.
  5. Computes recall and F1 for issues (and options where available).
  6. Writes a Markdown summary table to stdout (or --output file).

Environment:
    GITHUB_TOKEN  — optional but recommended to avoid rate limiting.
"""

import argparse
import json
import os
import re
import sys
import urllib.request
import urllib.error
from dataclasses import dataclass, field
from typing import Optional


def _llm_summarize_verdicts(verdicts: list[tuple[str, str, str]]) -> str:
    """
    Call the LiteLLM proxy to synthesize per-experiment verdicts into one paragraph.
    verdicts: list of (exp_id, scenario, verdict_text)
    Falls back to concatenation if the call fails.
    """
    base_url = os.environ.get("ANTHROPIC_BASE_URL", "https://litellm.prod.outshift.ai")
    api_key  = os.environ.get("ANTHROPIC_AUTH_TOKEN", "")
    model    = os.environ.get("SUMMARY_MODEL", "bedrock/global.anthropic.claude-haiku-4-5-20251001-v1:0")

    bullet_list = "\n".join(
        f"- **{exp_id} ({scenario}):** {verdict}"
        for exp_id, scenario, verdict in verdicts
    )
    prompt = (
        "You are summarizing results from a multi-agent negotiation experiment. "
        "Below are per-experiment verdicts. Write a single cohesive paragraph (4-6 sentences) "
        "that synthesizes the key findings across all experiments. Focus on patterns, "
        "differences between models/scenarios, and what the results mean for Mycelium's value. "
        "Do not use bullet points or headers — prose only.\n\n"
        f"{bullet_list}"
    )

    try:
        payload = json.dumps({
            "model": model,
            "max_tokens": 300,
            "messages": [{"role": "user", "content": prompt}],
        }).encode()
        req = urllib.request.Request(
            f"{base_url}/v1/chat/completions",
            data=payload,
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
        )
        resp = json.loads(urllib.request.urlopen(req, timeout=30).read())
        text = resp["choices"][0]["message"]["content"].strip()
        # Strip any markdown headers the LLM may have added
        text = re.sub(r"^#{1,3}\s+.*\n+", "", text).strip()
        return text
    except Exception as e:
        print(f"  WARNING: LLM verdict synthesis failed ({e}), falling back to concatenation.",
              file=sys.stderr)
        return " ".join(
            f"**{exp_id} ({scenario}):** {verdict}"
            for exp_id, scenario, verdict in verdicts
        )


# ---------------------------------------------------------------------------
# Ground truth source
# ---------------------------------------------------------------------------

GOLD_URL = (
    "https://api.github.com/repos/mycelium-io/agent-personas"
    "/contents/all_missions_set1_gold.json"
)

# Map scenario name fragments → gold standard ID
SCENARIO_TO_GOLD = {
    "ex01": "example_01",
    "ex02": "example_02",
    "ex03": "example_03",
    "ex04": "example_04",
    "ex05": "example_05",
    "ex06": "example_06",
    "ex07": "example_07",
    "ex08": "example_08",
    "ex09": "example_09",
    "quick_deal": "quick_deal",
    "cloud_platform": "cloud_platform",
    "hard_01": "hard_01",
    "hard_02": "hard_02",
    "hard_03": "hard_03",
    "hard_04": "hard_04",
    "hard_05": "hard_05",
}


def _gh_request(url: str) -> dict | list:
    req = urllib.request.Request(url)
    token = os.environ.get("GITHUB_TOKEN", "")
    if token:
        req.add_header("Authorization", f"token {token}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    with urllib.request.urlopen(req, timeout=30) as resp:
        return json.loads(resp.read().decode())


def fetch_gold_standard() -> dict:
    """Return {gold_id: entry} from mycelium-io/agent-personas."""
    import base64
    data = _gh_request(GOLD_URL)
    content = base64.b64decode(data["content"]).decode()
    entries = json.loads(content)
    return {e["id"]: e for e in entries}


# ---------------------------------------------------------------------------
# Gist fetching
# ---------------------------------------------------------------------------

def gist_id_from_url(url: str) -> str:
    url = url.strip().rstrip("/")
    return url.split("/")[-1]


def fetch_gist_files(gist_id: str) -> dict[str, str]:
    data = _gh_request(f"https://api.github.com/gists/{gist_id}")
    files = {}
    for fname, fdata in data.get("files", {}).items():
        if fdata.get("truncated"):
            req = urllib.request.Request(fdata["raw_url"])
            token = os.environ.get("GITHUB_TOKEN", "")
            if token:
                req.add_header("Authorization", f"token {token}")
            with urllib.request.urlopen(req, timeout=30) as resp:
                files[fname] = resp.read().decode(errors="replace")
        else:
            files[fname] = fdata.get("content", "")
    return files


def pick_file(files: dict[str, str], *patterns: str) -> Optional[str]:
    """Return content of the first filename containing any pattern (case-insensitive)."""
    for pat in patterns:
        pat_lower = pat.lower()
        for fname, content in files.items():
            if pat_lower in fname.lower():
                return content
    return None


# ---------------------------------------------------------------------------
# evaluation.md parsing
# ---------------------------------------------------------------------------

@dataclass
class EvalMetrics:
    exp_id: str = ""
    scenario: str = ""
    gist_url: str = ""
    before_consensus: str = ""
    after_consensus: str = ""
    before_rounds: str = ""
    after_rounds: str = ""
    before_score: str = ""
    after_score: str = ""
    before_ingest_events: str = ""
    after_ingest_events: str = ""
    before_tokens: str = ""
    after_tokens: str = ""
    before_issues_count: str = ""
    after_issues_count: str = ""
    before_negotiation_moves: str = ""
    after_negotiation_moves: str = ""
    gold_id: str = ""
    before_recall_issues: Optional[float] = None
    before_f1_issues: Optional[float] = None
    after_recall_issues: Optional[float] = None
    after_f1_issues: Optional[float] = None
    before_recall_options: Optional[float] = None
    before_f1_options: Optional[float] = None
    after_recall_options: Optional[float] = None
    after_f1_options: Optional[float] = None
    before_issues_found: list = field(default_factory=list)
    after_issues_found: list = field(default_factory=list)
    verdict: str = ""


def _clean_cell(s: str) -> str:
    return s.strip().strip("*").strip()


def parse_evaluation_md(content: str) -> EvalMetrics:
    m = EvalMetrics()

    # Header — two known formats:
    #   # Persona Before-and-After: ex07_investment_portfolio — exp-3812
    #   # Experiment exp-0228: ex03_personal_planning
    header_re = re.search(
        r"(?:Persona Before-and-After:\s*([\w_]+)\s*[—–-]+\s*(exp-\w+)"
        r"|Experiment\s+(exp-\w+):\s*([\w_]+))",
        content,
    )
    if header_re:
        if header_re.group(1):
            m.scenario = header_re.group(1)
            m.exp_id = header_re.group(2)
        else:
            m.exp_id = header_re.group(3)
            m.scenario = header_re.group(4)

    # Summary table — parse key→(before, after) pairs
    # Matches "## Summary", "## Comparison", or "## Before-and-After" sections
    in_summary = False
    header_seen = False
    sep_seen = False
    for line in content.splitlines():
        if re.search(r"^#{1,3}\s+(Summary|Comparison|Before.and.After)\b", line, re.IGNORECASE):
            in_summary = True
            header_seen = False
            sep_seen = False
            continue
        if in_summary:
            if re.match(r"^#{1,3}\s+", line) and not re.search(r"summary", line, re.IGNORECASE):
                in_summary = False
                continue
            if "|" not in line:
                continue
            cells = [c.strip() for c in line.split("|") if c.strip()]
            if not cells:
                continue
            if not header_seen and re.search(r"metric", cells[0], re.IGNORECASE):
                header_seen = True
                continue
            if header_seen and not sep_seen and re.match(r"^[-: ]+$", cells[0].replace("|", "")):
                sep_seen = True
                continue
            if not header_seen:
                continue
            if len(cells) < 3:
                continue
            key = _clean_cell(cells[0]).lower()
            before_val = _clean_cell(cells[1])
            after_val = _clean_cell(cells[2])

            if "consensus reached" in key or "consensus broken" in key:
                def _to_yes_no(v: str, invert: bool = False) -> str:
                    v_lower = v.lower()
                    is_yes = v_lower.startswith("yes") or (invert and v_lower.startswith("no"))
                    return "Yes" if is_yes else "No"
                m.before_consensus = _to_yes_no(before_val, invert="broken" in key)
                m.after_consensus = _to_yes_no(after_val, invert="broken" in key)
            elif ("rounds" in key or "messages to" in key) and not m.before_rounds:
                m.before_rounds = before_val
                m.after_rounds = after_val
            elif "negotiation moves" in key or ("negotiation" in key and "move" in key):
                m.before_negotiation_moves = before_val
                m.after_negotiation_moves = after_val
            elif "agent messages" in key and not m.after_negotiation_moves:
                m.before_negotiation_moves = before_val
                m.after_negotiation_moves = after_val
            elif "overall score" in key or ("overall" in key and "score" in key):
                m.before_score = before_val
                m.after_score = after_val
            elif "issues" in key and "identif" in key:
                m.before_issues_count = before_val
                m.after_issues_count = after_val

    # CFN ingest — may be in a separate table
    cfn_re = re.search(
        r"\|\s*Ingest events\s*\|\s*([^|]+)\|\s*([^|]+)\|",
        content, re.IGNORECASE,
    )
    if cfn_re:
        m.before_ingest_events = _clean_cell(cfn_re.group(1))
        m.after_ingest_events = _clean_cell(cfn_re.group(2))

    tok_re = re.search(
        r"\|\s*Est\.?\s*input tokens[^|]*\|\s*([^|]+)\|\s*([^|]+)\|",
        content, re.IGNORECASE,
    )
    if tok_re:
        m.before_tokens = _clean_cell(tok_re.group(1))
        m.after_tokens = _clean_cell(tok_re.group(2))

    # Verdict — text after "### Verdict" heading
    verdict_match = re.search(
        r"#{1,3}\s+Verdict\s*\n+([\s\S]+?)(?=\n#{1,3}\s|\Z)",
        content, re.IGNORECASE
    )
    if verdict_match:
        m.verdict = verdict_match.group(1).strip()

    # Fallback rounds label
    if not m.before_rounds:
        r_re = re.search(
            r"\|\s*Rounds to resolution\s*\|\s*([^|]+)\|\s*([^|]+)\|",
            content, re.IGNORECASE,
        )
        if r_re:
            m.before_rounds = _clean_cell(r_re.group(1))
            m.after_rounds = _clean_cell(r_re.group(2))

    return m


# ---------------------------------------------------------------------------
# Issue extraction from transcripts
# ---------------------------------------------------------------------------

_META_KEYS = frozenset({
    "plan", "action", "round", "participant_id", "error", "instruction",
    "broken", "can_counter_offer", "allowed_actions", "offer",
})


def _normalise(s: str) -> str:
    s = s.lower()
    s = re.sub(r"[^\w\s]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


def _extract_issues_from_ce_consensus(content: str) -> set[str]:
    """
    Extract issue keys from CognitiveEngine consensus/plan lines.

    Handles three transcript formats:
      1. [coordination_consensus] CognitiveEngine:\n{...}   (ex01/ex03/ex09 style)
      2. [CognitiveEngine] {...}                             (ex09 inline style)
      3. **CognitiveEngine:**\n{...}                        (exp-4919 markdown style)

    The consensus JSON often has an "assignments": {issue: value} dict and/or a
    "plan": "issue=value; issue=value" string. Both are 500-char hard-truncated
    when stored, so we use regex key extraction rather than full JSON parsing.
    """
    issues: set[str] = set()

    lines = content.splitlines()
    for i, line in enumerate(lines):
        # Identify lines that are CE consensus/plan payloads
        is_ce_json_line = (
            re.match(r'\[coordination_consensus\]', line)
            or re.match(r'\[CognitiveEngine\]\s*\{', line)
            or (re.match(r'\*\*CognitiveEngine:\*\*', line) and i + 1 < len(lines))
        )
        if not is_ce_json_line:
            continue

        # The JSON is either on this line (inline) or the next line
        json_line = line
        if re.match(r'\[coordination_consensus\]', line):
            # May be: "[coordination_consensus] CognitiveEngine: {JSON}" (inline)
            # or: "[coordination_consensus] CognitiveEngine:\n{JSON}" (next line)
            inline = re.sub(r'^\[coordination_consensus\]\s*CognitiveEngine:\s*', '', line).strip()
            if inline.startswith('{'):
                json_line = inline
            elif i + 1 < len(lines) and lines[i + 1].strip().startswith('{'):
                json_line = lines[i + 1]
            else:
                continue
        elif re.match(r'\*\*CognitiveEngine:\*\*', line):
            if i + 1 < len(lines):
                json_line = lines[i + 1]
            else:
                continue
        elif re.match(r'\[CognitiveEngine\]\s*\{', line):
            json_line = re.sub(r'^\[CognitiveEngine\]\s*', '', line)

        if not json_line.strip().startswith('{'):
            continue

        # Strategy A: try full JSON parse (works when not truncated)
        try:
            obj = json.loads(json_line)
            if isinstance(obj.get('assignments'), dict):
                issues.update(
                    k for k in obj['assignments']
                    if k.lower() not in _META_KEYS
                )
                continue  # assignments is authoritative — skip plan string
        except (json.JSONDecodeError, ValueError):
            pass

        # Strategy B: truncated line — extract from "assignments": { ... } block via regex
        # Match "key": "value" pairs within the assignments value
        assign_block = re.search(r'"assignments"\s*:\s*\{([^}]*)', json_line)
        if assign_block:
            for key_match in re.finditer(r'"([^"]{2,80})":', assign_block.group(1)):
                k = key_match.group(1)
                if k.lower() not in _META_KEYS:
                    issues.add(k)
            if issues:
                continue  # found assignments keys — skip plan string

        # Strategy C: extract from "plan": "key=value; key=value" string
        # The plan string format is: issue_name=resolved_value; issue_name=...
        plan_match = re.search(r'"plan"\s*:\s*"([^"]*)', json_line)
        if plan_match:
            plan_str = plan_match.group(1)
            # Each segment is: issue_label=resolved_value (separated by semicolons)
            for segment in plan_str.split(';'):
                segment = segment.strip()
                if '=' in segment:
                    key = segment.split('=', 1)[0].strip()
                    if 2 < len(key) <= 80 and key.lower() not in _META_KEYS:
                        issues.add(key)

    return issues


def extract_issues_from_session_transcript(content: str) -> list[str]:
    """
    Extract negotiation issue keys from a Mycelium session transcript.

    Priority order:
      1. CognitiveEngine consensus/plan lines (assignments dict or plan string) —
         these are the definitive resolved issue set from a completed CE session.
      2. Offer JSON objects (current_offer / offer dicts from tick messages) —
         used when consensus lines are absent or parse to nothing.
      3. Truncated-line regex fallback on offer lines.
    """
    issues: set[str] = set()

    # Strategy 1: CE consensus/plan lines (most reliable — explicit final issue set)
    ce_issues = _extract_issues_from_ce_consensus(content)
    if ce_issues:
        issues.update(ce_issues)
        # Still continue to pick up offer-tick keys in case consensus was partial/truncated
        # but CE consensus is the primary signal

    # Strategy 2: parse complete JSON objects (tick payloads, offer responses)
    for raw in _iter_json_objects(content):
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            pass
        else:
            for offer in _find_offers(obj):
                issues.update(k for k in offer if k.lower() not in _META_KEYS)

    # Strategy 3: for truncated lines, extract keys via regex from known offer blocks
    for line in content.splitlines():
        if not line.startswith("{"):
            continue
        for key_match in re.finditer(r'"([^"]{2,80})":\s*"', line):
            key = key_match.group(1)
            if key.lower() not in _META_KEYS:
                issues.add(key)

    # Filter metadata keys
    issues = {
        k for k in issues
        if not re.match(
            r"^(error|instruction|plan|action|round|participant_id|broken"
            r"|can_counter_offer|allowed_actions|offer|payload|current_offer)$",
            k.lower(),
        )
    }

    return sorted(issues)


def _iter_json_objects(text: str):
    """Yield top-level JSON object strings from text using brace matching."""
    depth = 0
    start = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}" and depth > 0:
            depth -= 1
            if depth == 0 and start is not None:
                yield text[start:i + 1]
                start = None


def _find_offers(obj) -> list[dict]:
    """Recursively find dicts that look like negotiation offer maps."""
    found = []
    if not isinstance(obj, dict):
        return found
    # [coordination_tick] payload.current_offer — dict of {issue: value}
    if "current_offer" in obj and isinstance(obj["current_offer"], dict):
        found.append(obj["current_offer"])
    # [coordination_consensus] assignments
    if "assignments" in obj and isinstance(obj["assignments"], dict):
        found.append(obj["assignments"])
    # [direct] agent response: {"offer": {issue: value}} or {"action": "...", "offer": {...}}
    if "offer" in obj and isinstance(obj["offer"], dict):
        offer = obj["offer"]
        # Only treat as issue map if values are strings (not nested dicts/lists)
        if all(isinstance(v, (str, int, float)) for v in offer.values()):
            found.append(offer)
    for v in obj.values():
        if isinstance(v, dict):
            found.extend(_find_offers(v))
    return found


def _extract_options_from_ce_consensus(content: str) -> dict[str, set[str]]:
    """
    Extract {issue: {resolved_value}} from CE consensus/plan lines.

    The CE's final "assignments" dict and "plan" key=value string both encode
    the single agreed value per issue — adding these to the options dict gives
    the value matcher something to compare against gold option strings even when
    no offer-tick payloads are present (ex01, ex07, ex08).
    """
    options: dict[str, set[str]] = {}

    lines = content.splitlines()
    for i, line in enumerate(lines):
        is_ce_json_line = (
            re.match(r'\[coordination_consensus\]', line)
            or re.match(r'\[CognitiveEngine\]\s*\{', line)
            or (re.match(r'\*\*CognitiveEngine:\*\*', line) and i + 1 < len(lines))
        )
        if not is_ce_json_line:
            continue

        if re.match(r'\[coordination_consensus\]', line):
            inline = re.sub(r'^\[coordination_consensus\]\s*CognitiveEngine:\s*', '', line).strip()
            json_line = inline if inline.startswith('{') else (
                lines[i + 1] if i + 1 < len(lines) and lines[i + 1].strip().startswith('{') else None
            )
        elif re.match(r'\*\*CognitiveEngine:\*\*', line):
            json_line = lines[i + 1] if i + 1 < len(lines) else None
        else:
            json_line = re.sub(r'^\[CognitiveEngine\]\s*', '', line)

        if not json_line or not json_line.strip().startswith('{'):
            continue

        # Strategy A: full JSON parse — use assignments dict directly
        try:
            obj = json.loads(json_line)
            if isinstance(obj.get('assignments'), dict):
                for k, v in obj['assignments'].items():
                    if k.lower() not in _META_KEYS and isinstance(v, str) and v.strip():
                        options.setdefault(k, set()).add(v.strip())
                continue
        except (json.JSONDecodeError, ValueError):
            pass

        # Strategy B: truncated — regex-extract key: "value" pairs from assignments block
        assign_block = re.search(r'"assignments"\s*:\s*\{([^}]*)', json_line)
        if assign_block:
            for kv in re.finditer(r'"([^"]{2,80})"\s*:\s*"([^"]{2,})"', assign_block.group(1)):
                k, v = kv.group(1), kv.group(2)
                if k.lower() not in _META_KEYS:
                    options.setdefault(k, set()).add(v.strip())
            if options:
                continue

        # Strategy C: plan string — key=value; key=value
        plan_match = re.search(r'"plan"\s*:\s*"([^"]*)', json_line)
        if plan_match:
            for segment in plan_match.group(1).split(';'):
                segment = segment.strip()
                if '=' in segment:
                    k, _, v = segment.partition('=')
                    k, v = k.strip(), v.strip()
                    if 2 < len(k) <= 80 and k.lower() not in _META_KEYS and v:
                        options.setdefault(k, set()).add(v)

    return options


def extract_options_from_session_transcript(content: str) -> dict[str, set[str]]:
    """Return {issue_key: {option_values}} from all offer snapshots and CE consensus."""
    options: dict[str, set[str]] = {}

    # CE consensus resolved values — the single agreed value per issue
    for k, vals in _extract_options_from_ce_consensus(content).items():
        options.setdefault(k, set()).update(vals)

    # Offer-tick payloads — all values proposed across rounds
    for raw in _iter_json_objects(content):
        try:
            obj = json.loads(raw)
        except (json.JSONDecodeError, ValueError):
            continue
        for offer in _find_offers(obj):
            for k, v in offer.items():
                if k.lower() in _META_KEYS:
                    continue
                if isinstance(v, str) and v.strip():
                    options.setdefault(k, set()).add(v.strip())
    return options


def extract_issues_from_before_transcript(content: str, gold_issues: list[str]) -> list[str]:
    """
    For unstructured before-case transcripts, detect gold issues by keyword
    presence.  An issue is considered found if the majority of its significant
    words appear in the transcript.
    """
    found = []
    content_norm = _normalise(content)
    for issue in gold_issues:
        words = [w for w in _normalise(issue).split() if len(w) > 3]
        if not words:
            continue
        hit_ratio = sum(1 for w in words if w in content_norm) / len(words)
        if hit_ratio >= 0.6:
            found.append(issue)
    return found


def extract_options_from_before_transcript(
    content: str, gold_options: dict
) -> dict[str, set[str]]:
    """Find gold option strings in the before transcript via keyword overlap."""
    options: dict[str, set[str]] = {}
    content_norm = _normalise(content)
    for issue, opt_list in gold_options.items():
        for opt in opt_list:
            words = [w for w in _normalise(opt).split() if len(w) > 4]
            if len(words) >= 3 and sum(1 for w in words if w in content_norm) / len(words) >= 0.6:
                options.setdefault(issue, set()).add(opt)
    return options


# ---------------------------------------------------------------------------
# Embedding similarity (BAAI/bge-small-en-v1.5 via fastembed)
# ---------------------------------------------------------------------------

class _EmbedMatcher:
    """
    Lazily loads fastembed from the Mycelium backend venv and caches cosine
    similarity lookups.  Falls back to Jaccard if fastembed is unavailable.

    The backend venv path is auto-detected, or can be overridden with
    MYCELIUM_EMBED_VENV=/path/to/.venv.
    """

    _VENV_CANDIDATES = [
        os.path.expanduser("~/mycelium/fastapi-backend/.venv"),
        "/home/ubuntu/mycelium/fastapi-backend/.venv",
    ]
    _MODEL_NAME = "BAAI/bge-small-en-v1.5"
    _CACHE_DIR   = os.path.expanduser("~/.cache/fastembed")
    _THRESHOLD   = 0.70

    def __init__(self) -> None:
        self._model = None            # fastembed TextEmbedding or None if unavailable
        self._vec_cache: dict[str, list[float]] = {}
        self._available: bool | None = None   # None = untried

    def _try_load(self) -> bool:
        if self._available is not None:
            return self._available
        # 1. Try direct import first (script may already be running in a venv that has it)
        try:
            from fastembed import TextEmbedding  # noqa: PLC0415
            self._model = TextEmbedding(
                model_name=self._MODEL_NAME,
                cache_dir=self._CACHE_DIR,
            )
            self._available = True
            return True
        except (ImportError, Exception):
            pass
        # 2. Inject the backend venv's site-packages into sys.path
        venv_root = os.environ.get("MYCELIUM_EMBED_VENV", "")
        candidates = [venv_root] if venv_root else self._VENV_CANDIDATES
        for venv in candidates:
            sp = os.path.join(venv, "lib", "python3.12", "site-packages")
            if not os.path.isdir(sp):
                continue
            if sp not in sys.path:
                sys.path.insert(0, sp)
            try:
                from fastembed import TextEmbedding  # noqa: PLC0415
                self._model = TextEmbedding(
                    model_name=self._MODEL_NAME,
                    cache_dir=self._CACHE_DIR,
                )
                self._available = True
                return True
            except (ImportError, Exception):
                if sp in sys.path:
                    sys.path.remove(sp)
        self._available = False
        return False

    def _embed(self, texts: list[str]) -> list[list[float]]:
        """Embed a batch, using the cache for already-seen strings."""
        new_texts = [t for t in texts if t not in self._vec_cache]
        if new_texts:
            vecs = list(self._model.embed(new_texts))
            for t, v in zip(new_texts, vecs):
                self._vec_cache[t] = v.tolist() if hasattr(v, "tolist") else list(v)
        return [self._vec_cache[t] for t in texts]

    @staticmethod
    def _cosine(a: list[float], b: list[float]) -> float:
        dot = sum(x * y for x, y in zip(a, b))
        na  = sum(x * x for x in a) ** 0.5
        nb  = sum(x * x for x in b) ** 0.5
        return dot / (na * nb) if na and nb else 0.0

    def best_similarity(self, candidate: str, gold_list: list[str]) -> float:
        """Return the highest cosine similarity between candidate and any gold label."""
        if not self._try_load() or not gold_list:
            return 0.0
        vecs = self._embed([candidate, *gold_list])
        cv = vecs[0]
        return max(self._cosine(cv, gv) for gv in vecs[1:])

    def matches(self, candidate: str, gold_list: list[str]) -> bool:
        sim = self.best_similarity(candidate, gold_list)
        return sim >= self._THRESHOLD


_embed_matcher = _EmbedMatcher()


# ---------------------------------------------------------------------------
# Recall / F1
# ---------------------------------------------------------------------------

def _jaccard(a: str, b: str) -> float:
    aw = set(_normalise(a).split())
    bw = set(_normalise(b).split())
    if not aw or not bw:
        return 0.0
    return len(aw & bw) / len(aw | bw)


def _contains_match(candidate: str, gold: str) -> bool:
    """True if all significant words of the shorter string appear in the longer."""
    cw = set(_normalise(candidate).split())
    gw = set(_normalise(gold).split())
    sig = {w for w in gw if len(w) > 3}
    if not sig:
        return False
    return sum(1 for w in sig if w in cw) / len(sig) >= 0.8


def _fuzzy_match(candidate: str, gold_list: list[str], threshold: float = 0.3) -> bool:
    # Try embedding similarity first (semantically richer, handles label paraphrasing)
    if _embed_matcher._available is not False and _embed_matcher.matches(candidate, gold_list):
        return True
    # Jaccard / word-overlap fallback (works without fastembed)
    return any(
        _contains_match(candidate, g) or _jaccard(candidate, g) >= threshold
        for g in gold_list
    )


def compute_issue_metrics(
    found: list[str], gold: list[str]
) -> tuple[float, float, float]:
    if not gold:
        return 0.0, 0.0, 0.0
    tp = sum(1 for f in found if _fuzzy_match(f, gold))
    precision = tp / len(found) if found else 0.0
    recall = tp / len(gold)
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) > 0 else 0.0
    return precision, recall, f1


def compute_option_metrics(
    found_options: dict[str, set[str]],
    gold_options: dict[str, list[str]],
    gold_issues: list[str],
) -> tuple[float, float, float]:
    if not gold_issues or not gold_options:
        return 0.0, 0.0, 0.0
    precisions, recalls = [], []
    for issue in gold_issues:
        gold_opts = gold_options.get(issue, [])
        if not gold_opts:
            continue
        # Find found options for this issue (fuzzy key match + embedding)
        found_opts: set[str] = set()
        for fk, fv in found_options.items():
            if _fuzzy_match(fk, [issue]) or (
                _embed_matcher._try_load()
                and _embed_matcher.best_similarity(fk, [issue]) >= 0.70
            ):
                found_opts |= fv
        tp = sum(
            1 for go in gold_opts
            if any(
                _embed_matcher.best_similarity(fo, [go]) >= 0.65
                if _embed_matcher._try_load()
                else _jaccard(fo, go) >= 0.4
                for fo in found_opts
            )
        )
        precisions.append(tp / len(found_opts) if found_opts else 0.0)
        recalls.append(tp / len(gold_opts))
    if not precisions:
        return 0.0, 0.0, 0.0
    avg_p = sum(precisions) / len(precisions)
    avg_r = sum(recalls) / len(recalls)
    f1 = 2 * avg_p * avg_r / (avg_p + avg_r) if (avg_p + avg_r) > 0 else 0.0
    return avg_p, avg_r, f1


# ---------------------------------------------------------------------------
# Scenario → gold ID
# ---------------------------------------------------------------------------

def map_scenario_to_gold_id(scenario: str) -> Optional[str]:
    s = scenario.lower()
    for fragment, gold_id in SCENARIO_TO_GOLD.items():
        if fragment in s:
            return gold_id
    return None


# ---------------------------------------------------------------------------
# Per-gist processing
# ---------------------------------------------------------------------------

def process_gist(gist_url: str, gold: dict) -> Optional[EvalMetrics]:
    gist_id = gist_id_from_url(gist_url)
    print(f"  Fetching gist {gist_id} ...", file=sys.stderr)
    try:
        files = fetch_gist_files(gist_id)
    except urllib.error.HTTPError as e:
        print(f"  ERROR fetching gist {gist_id}: {e}", file=sys.stderr)
        return None

    eval_content = pick_file(files, "evaluation.md")
    if not eval_content:
        print(f"  WARNING: no evaluation.md in gist {gist_id}", file=sys.stderr)
        return None

    m = parse_evaluation_md(eval_content)
    m.gist_url = gist_url

    gold_id = map_scenario_to_gold_id(m.scenario)
    if not gold_id or gold_id not in gold:
        print(
            f"  SKIP {m.exp_id or gist_id}: scenario '{m.scenario}' "
            "has no ground truth entry",
            file=sys.stderr,
        )
        return None

    m.gold_id = gold_id
    gold_entry = gold[gold_id]
    gold_issues = gold_entry["gold_issues"]
    gold_options = gold_entry.get("gold_options", {})

    # Parse ingest events directly from stats JSON files in the gist
    for label in ("before", "after"):
        stats_content = pick_file(files, f"{label}-ingest-stats")
        if stats_content:
            try:
                stats = json.loads(stats_content)
                t = stats.get("total", {})
                tokens = t.get("estimated_cfn_knowledge_input_tokens", 0)
                tokens_str = f"{round(tokens / 1000)}k" if tokens >= 1000 else str(tokens)
                if label == "before":
                    m.before_tokens = tokens_str
                else:
                    m.after_tokens = tokens_str
            except (json.JSONDecodeError, KeyError):
                pass

    # Negotiation moves — computed directly from transcripts (more reliable than eval.md table)
    before_transcript_content = pick_file(files, "before-transcript") or ""
    after_session_content = pick_file(files, "after-session-transcript", "session-transcript") or ""
    after_transcript_content = pick_file(files, "after-transcript") or ""

    # Before: every agent chat message is a negotiation move.
    # Supports two heading formats:
    #   **exp-XXXX-agent:**                (bold inline label, older experiments)
    #   ### [timestamp] exp-XXXX-agent    (timestamp heading, newer experiments)
    before_move_count = sum(
        1 for line in before_transcript_content.splitlines()
        if (
            re.match(r"^\*\*exp-[^*]+\*\*:$", line.rstrip())
            or re.match(r"^#{2,3}\s+\[\d{4}-\d{2}-\d{2}.*\]\s+exp-", line)
        )
    )
    if before_move_count:
        m.before_negotiation_moves = str(before_move_count)

    # After: count 'direct' messages in session transcript (agent accept/reject/propose actions)
    after_direct_count = sum(
        1 for line in after_session_content.splitlines()
        if line.startswith("[direct]")
    )
    if after_direct_count:
        m.after_negotiation_moves = str(after_direct_count)

    # After case — structured session transcript preferred
    after_session = after_session_content
    after_transcript = after_transcript_content
    after_source = after_session or after_transcript or ""

    after_issues = extract_issues_from_session_transcript(after_source)
    after_options = extract_options_from_session_transcript(after_source)
    m.after_issues_found = after_issues

    # Before case — keyword search in free-chat transcript
    before_source = before_transcript_content
    before_issues = extract_issues_from_before_transcript(before_source, gold_issues)
    before_options = extract_options_from_before_transcript(before_source, gold_options)
    m.before_issues_found = before_issues

    # Metrics
    _, m.before_recall_issues, m.before_f1_issues = compute_issue_metrics(
        before_issues, gold_issues
    )
    _, m.after_recall_issues, m.after_f1_issues = compute_issue_metrics(
        after_issues, gold_issues
    )
    if gold_options:
        _, m.before_recall_options, m.before_f1_options = compute_option_metrics(
            before_options, gold_options, gold_issues
        )
        _, m.after_recall_options, m.after_f1_options = compute_option_metrics(
            after_options, gold_options, gold_issues
        )

    return m


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _pct(v: Optional[float]) -> str:
    return "N/A" if v is None else f"{v:.0%}"


def _fmt(v: str, max_len: int = 30) -> str:
    v = v.strip()
    return v if len(v) <= max_len else v[: max_len - 1] + "…"


def build_report(results: list[EvalMetrics], total_inputs: int) -> str:
    lines: list[str] = []
    lines.append("# Persona Before-and-After: Aggregate Summary\n")
    lines.append(
        f"**Gists processed:** {len(results)} with ground truth "
        f"(out of {total_inputs} inputs)\n"
    )

    if not results:
        lines.append("_No results to display._\n")
        return "\n".join(lines)

    # --- Main table ---
    lines.append("## Results\n")
    cols = [
        "Exp",
        "Scenario",
        "Gold ID",
        "Before Consensus Reached?",
        "After Consensus Reached?",
        "Before Negotiation Moves",
        "After Negotiation Moves",
        "Before #Tokens",
        "After #Tokens",
        "Before Issues Found",
        "After Issues Found",
        "Before Issue Recall",
        "Before Issue F1",
        "After Issue Recall",
        "After Issue F1",
        "Before Option Recall",
        "Before Option F1",
        "After Option Recall",
        "After Option F1",
        "Gist",
    ]
    lines.append("| " + " | ".join(cols) + " |")
    lines.append("| " + " | ".join("---" for _ in cols) + " |")

    for m in results:
        cells = [
            m.exp_id,
            _fmt(m.scenario, 25),
            m.gold_id,
            _fmt(m.before_consensus),
            _fmt(m.after_consensus),
            _fmt(m.before_negotiation_moves, 10),
            _fmt(m.after_negotiation_moves, 10),
            _fmt(m.before_tokens, 15),
            _fmt(m.after_tokens, 15),
            str(len(m.before_issues_found)),
            str(len(m.after_issues_found)),
            _pct(m.before_recall_issues),
            _pct(m.before_f1_issues),
            _pct(m.after_recall_issues),
            _pct(m.after_f1_issues),
            _pct(m.before_recall_options),
            _pct(m.before_f1_options),
            _pct(m.after_recall_options),
            _pct(m.after_f1_options),
            f"[gist]({m.gist_url})",
        ]
        lines.append("| " + " | ".join(cells) + " |")

    lines.append("")

    # --- Verdicts ---
    lines.append("## Verdict\n")
    verdict_inputs = [(m.exp_id, m.scenario, m.verdict) for m in results if m.verdict]
    if verdict_inputs:
        print("  Synthesizing verdicts with LLM ...", file=sys.stderr)
        combined = _llm_summarize_verdicts(verdict_inputs)
        lines.append(combined + "\n")
    else:
        lines.append("_No verdicts found in evaluation files._\n")

    return "\n".join(lines)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def load_urls(sources: list[str]) -> list[str]:
    urls = []
    for src in sources:
        if os.path.isfile(src) and not src.startswith("http"):
            with open(src) as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        urls.append(line)
        else:
            urls.append(src)
    return urls


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Aggregate persona-before-and-after gist results against ground truth."
    )
    parser.add_argument(
        "sources",
        nargs="+",
        help="Gist URLs, gist IDs, or a .txt file with one URL/ID per line.",
    )
    parser.add_argument(
        "--output", "-o",
        default=None,
        help="Write Markdown summary to this file (default: stdout).",
    )
    args = parser.parse_args()

    gist_urls = load_urls(args.sources)
    if not gist_urls:
        print("ERROR: no gist URLs provided.", file=sys.stderr)
        sys.exit(1)

    print(f"Fetching ground truth from mycelium-io/agent-personas ...", file=sys.stderr)
    try:
        gold = fetch_gold_standard()
    except Exception as e:
        print(f"ERROR fetching ground truth: {e}", file=sys.stderr)
        sys.exit(1)
    print(f"  Loaded {len(gold)} gold entries.", file=sys.stderr)

    results = []
    for url in gist_urls:
        result = process_gist(url, gold)
        if result is not None:
            results.append(result)

    report = build_report(results, len(gist_urls))

    if args.output:
        with open(args.output, "w") as f:
            f.write(report)
        print(f"\nSummary written to {args.output}", file=sys.stderr)
    else:
        print(report)


if __name__ == "__main__":
    main()
