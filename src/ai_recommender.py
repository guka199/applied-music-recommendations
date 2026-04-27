"""
AI-powered recommendation layer for VibeFinder.

Two-stage pipeline:
  1. parse_natural_language — converts a free-text query into a structured profile dict
  2. ai_rerank — re-orders the weighted-scorer's top-10 candidates using Claude's
     musical reasoning

AIRecommender.recommend() orchestrates both stages and falls back to the pure
weighted scorer if any Anthropic API call fails.
"""

import json
import os
from typing import Dict, List, Optional, Tuple

import anthropic

from logger import setup_logger
from recommender import load_songs, recommend_songs, DEFAULT_WEIGHTS

logger = setup_logger("vibefinder.ai")

# ---------------------------------------------------------------------------
# System prompt — injected with cache_control so it is eligible for prompt
# caching once the catalog grows past the ~4096-token minimum.
# ---------------------------------------------------------------------------
SYSTEM_PROMPT = """\
You are VibeFinder's specialized music recommendation expert.
Your job is to understand how listeners describe their mood, activity, and taste,
then translate that into the precise audio feature dimensions the system uses:

  genre      — one of: pop, lofi, rock, ambient, jazz, synthwave, indie pop,
                        hip-hop, classical, country, metal, reggae, r&b, edm, blues
  mood       — one of: happy, chill, intense, relaxed, moody, focused, confident,
                        peaceful, nostalgic, aggressive, romantic, euphoric, melancholy
  energy     — float 0.0–1.0  (0 = very calm, 1 = maximum energy)
  valence    — float 0.0–1.0  (0 = dark/sad, 1 = bright/joyful)
  tempo_bpm  — integer 60–200

When re-ranking candidates, explain your musical reasoning concisely.
Always respond with valid JSON matching the schema provided in each request.
"""

# JSON schema for parse_natural_language output
_PROFILE_SCHEMA = {
    "type": "object",
    "properties": {
        "genre":     {"type": "string"},
        "mood":      {"type": "string"},
        "energy":    {"type": "number"},
        "valence":   {"type": "number"},
        "tempo_bpm": {"type": "number"},
    },
    "required": ["genre", "mood", "energy", "valence", "tempo_bpm"],
}

# JSON schema for ai_rerank output
_RERANK_SCHEMA = {
    "type": "object",
    "properties": {
        "ranked_titles": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Song titles in descending order of recommendation strength.",
        },
        "reasoning": {
            "type": "string",
            "description": "One-paragraph explanation of the ranking decision.",
        },
    },
    "required": ["ranked_titles", "reasoning"],
}


def parse_natural_language(
    user_input: str,
    client: anthropic.Anthropic,
) -> Dict:
    """Convert a free-text listening preference into a structured profile dict.

    Returns a dict with keys: genre, mood, energy, valence, tempo_bpm.
    Raises anthropic.APIError on network/auth failure (caller handles fallback).
    """
    logger.debug("parse_natural_language called with input: %r", user_input)

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=512,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"Convert this listening preference to a structured profile:\n\n"
                    f'"{user_input}"\n\n'
                    "Respond with JSON only, matching the provided schema."
                ),
            }
        ],
        output_config={
            "format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "user_profile",
                    "schema": _PROFILE_SCHEMA,
                    "strict": True,
                },
            }
        },
    )

    raw = response.content[0].text
    profile = json.loads(raw)
    logger.info("Parsed profile: %s", profile)
    return profile


def ai_rerank(
    user_description: str,
    candidates: List[Tuple[Dict, float, str]],
    client: anthropic.Anthropic,
) -> List[Tuple[Dict, float, str]]:
    """Re-rank weighted-scorer candidates using Claude's musical reasoning.

    candidates — list of (song_dict, score, explanation) tuples (up to 10)
    Returns the same tuples reordered, filtered to only confirmed catalog songs.
    Any candidates the AI omits are appended at the end as a safety net.
    Raises anthropic.APIError on failure (caller handles fallback).
    """
    catalog_snippet = "\n".join(
        f"- \"{s['title']}\" by {s['artist']} "
        f"(genre={s['genre']}, mood={s['mood']}, energy={s['energy']:.2f}, "
        f"valence={s['valence']:.2f}, tempo={s['tempo_bpm']} bpm)  [score={score:.2f}]"
        for s, score, _ in candidates
    )

    logger.debug("ai_rerank called with %d candidates", len(candidates))

    response = client.messages.create(
        model="claude-opus-4-7",
        max_tokens=1024,
        system=[
            {
                "type": "text",
                "text": SYSTEM_PROMPT,
                "cache_control": {"type": "ephemeral"},
            }
        ],
        messages=[
            {
                "role": "user",
                "content": (
                    f"A listener said: \"{user_description}\"\n\n"
                    "The weighted scorer pre-selected these candidates:\n"
                    f"{catalog_snippet}\n\n"
                    "Re-rank them from best to worst match for this listener. "
                    "Use your musical expertise — consider how energy, mood, and genre "
                    "interact with what the listener described. "
                    "Return ONLY the exact song titles as listed above."
                ),
            }
        ],
        output_config={
            "format": {
                "type": "json_schema",
                "json_schema": {
                    "name": "rerank_result",
                    "schema": _RERANK_SCHEMA,
                    "strict": True,
                },
            }
        },
    )

    raw = response.content[0].text
    result = json.loads(raw)
    logger.info("AI re-rank reasoning: %s", result.get("reasoning", ""))

    # Build a lookup from title → candidate tuple (guardrail: only catalog songs)
    title_map: Dict[str, Tuple[Dict, float, str]] = {
        s["title"]: (s, score, expl) for s, score, expl in candidates
    }

    reranked: List[Tuple[Dict, float, str]] = []
    seen_titles = set()
    for title in result.get("ranked_titles", []):
        if title in title_map and title not in seen_titles:
            reranked.append(title_map[title])
            seen_titles.add(title)
        else:
            logger.warning("AI returned unknown or duplicate title %r — skipping", title)

    # Safety net: append any candidates the AI omitted
    for title, tup in title_map.items():
        if title not in seen_titles:
            logger.warning("AI omitted %r — appending at end", title)
            reranked.append(tup)

    return reranked


class AIRecommender:
    """Orchestrates the two-stage NL-parse → weighted-score → AI-rerank pipeline."""

    def __init__(self, songs: List[Dict]):
        self.songs = songs
        self.client = anthropic.Anthropic(api_key=os.environ.get("ANTHROPIC_API_KEY"))

    def recommend(
        self, user_description: str, k: int = 5
    ) -> Tuple[List[Tuple[Dict, float, str]], Optional[Dict], bool]:
        """Run the full AI pipeline and return (top_k_results, parsed_profile, fallback_used).

        On any API or JSON error, falls back to the pure weighted scorer.
        parsed_profile is None when fallback is used.
        """
        try:
            # Stage 1: NL → structured profile
            profile = parse_natural_language(user_description, self.client)

            # Stage 2: weighted scorer → top-10 candidates (using the parsed profile)
            candidates = recommend_songs(profile, self.songs, k=10)

            # Stage 3: AI re-rank
            reranked = ai_rerank(user_description, candidates, self.client)

            return reranked[:k], profile, False

        except (anthropic.APIError, json.JSONDecodeError, KeyError) as exc:
            logger.warning(
                "AI pipeline failed (%s: %s) — falling back to weighted scorer",
                type(exc).__name__,
                exc,
            )
            # Fallback: derive a basic profile from keyword heuristics for weighted scorer
            fallback_profile = _keyword_fallback(user_description)
            results = recommend_songs(fallback_profile, self.songs, k=k)
            return results, None, True


def _keyword_fallback(text: str) -> Dict:
    """Derive a rough profile from keywords when the AI is unavailable."""
    text_lower = text.lower()
    genre_keywords = {
        "pop": "pop", "lofi": "lofi", "rock": "rock", "jazz": "jazz",
        "classical": "classical", "edm": "edm", "hip-hop": "hip-hop",
        "hip hop": "hip-hop", "metal": "metal", "reggae": "reggae",
        "blues": "blues", "country": "country", "ambient": "ambient",
    }
    genre = next((v for k, v in genre_keywords.items() if k in text_lower), "pop")

    energy = 0.8 if any(w in text_lower for w in ("workout", "gym", "energy", "hype", "intense", "pump")) else 0.5
    if any(w in text_lower for w in ("chill", "relax", "study", "focus", "calm", "sleep")):
        energy = 0.35

    mood = "happy"
    for kw, m in [("sad", "melancholy"), ("melancholy", "melancholy"), ("chill", "chill"),
                  ("study", "focused"), ("focus", "focused"), ("intense", "intense"),
                  ("romantic", "romantic"), ("peaceful", "peaceful")]:
        if kw in text_lower:
            mood = m
            break

    return {"genre": genre, "mood": mood, "energy": energy, "valence": 0.6, "tempo_bpm": 100}
