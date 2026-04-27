"""
AI-powered recommendation layer for VibeFinder.

Uses Groq's free API (LLaMA 3.3 70B) for two stages:
  1. parse_natural_language — converts a free-text query into a structured profile dict
  2. ai_rerank — re-orders the weighted-scorer's top-10 candidates using
     musical reasoning

AIRecommender.recommend() orchestrates both stages and falls back to the pure
weighted scorer if any API call fails.

Get a free Groq API key at: https://console.groq.com
"""

import json
import os
from typing import Dict, List, Optional, Tuple

from groq import Groq, APIError

from logger import setup_logger
from recommender import recommend_songs

logger = setup_logger("vibefinder.ai")

MODEL = "llama-3.3-70b-versatile"

SYSTEM_PROMPT = """\
You are VibeFinder's music recommendation expert.
Your job is to understand how listeners describe their mood, activity, and taste,
then translate that into precise audio feature dimensions.

Valid genres: pop, lofi, rock, ambient, jazz, synthwave, indie pop,
              hip-hop, classical, country, metal, reggae, r&b, edm, blues
Valid moods:  happy, chill, intense, relaxed, moody, focused, confident,
              peaceful, nostalgic, aggressive, romantic, euphoric, melancholy
energy     — float 0.0–1.0  (0 = very calm, 1 = maximum energy)
valence    — float 0.0–1.0  (0 = dark/sad, 1 = bright/joyful)
tempo_bpm  — integer 60–200

Always respond with valid JSON only — no markdown, no code fences, no extra text.
"""


def parse_natural_language(user_input: str, client: Groq) -> Dict:
    """Convert a free-text listening preference into a structured profile dict.

    Returns a dict with keys: genre, mood, energy, valence, tempo_bpm.
    Raises groq.APIError on network/auth failure (caller handles fallback).
    """
    logger.debug("parse_natural_language called with input: %r", user_input)

    prompt = (
        f'Convert this listening preference into a JSON profile:\n\n"{user_input}"\n\n'
        "Return ONLY a JSON object with exactly these keys: "
        "genre, mood, energy (float 0-1), valence (float 0-1), tempo_bpm (int). "
        "No explanation, no markdown — raw JSON only."
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.2,
        max_tokens=256,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    profile = json.loads(raw)
    logger.info("Parsed profile: %s", profile)
    return profile


def ai_rerank(
    user_description: str,
    candidates: List[Tuple[Dict, float, str]],
    client: Groq,
) -> Tuple[List[Tuple[Dict, float, str]], Dict[str, float]]:
    """Re-rank weighted-scorer candidates using LLaMA's musical reasoning.

    Returns (reranked_tuples, confidence_scores).
    Guardrail: any title not in the catalog is silently dropped.
    Safety net: any candidate the AI omits is appended at the end.
    Raises groq.APIError on failure (caller handles fallback).
    """
    catalog_snippet = "\n".join(
        f'- "{s["title"]}" by {s["artist"]} '
        f"(genre={s['genre']}, mood={s['mood']}, energy={s['energy']:.2f}, "
        f"valence={s['valence']:.2f}, tempo={s['tempo_bpm']} bpm)  [score={score:.2f}]"
        for s, score, _ in candidates
    )

    logger.debug("ai_rerank called with %d candidates", len(candidates))

    prompt = (
        f'A listener said: "{user_description}"\n\n'
        f"Candidate songs:\n{catalog_snippet}\n\n"
        "Re-rank these songs from best to worst match for this listener. "
        "Use musical expertise — consider how energy, mood, and genre interact "
        "with what the listener described. "
        "Return ONLY a JSON object with exactly these keys:\n"
        '  "ranked_titles": [list of exact song titles in order],\n'
        '  "confidence_scores": {title: float 0.0-1.0},\n'
        '  "reasoning": "one sentence explaining the top pick"\n'
        "Use ONLY the exact song titles listed above. No markdown, raw JSON only."
    )

    response = client.chat.completions.create(
        model=MODEL,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user",   "content": prompt},
        ],
        temperature=0.3,
        max_tokens=1024,
        response_format={"type": "json_object"},
    )

    raw = response.choices[0].message.content
    result = json.loads(raw)
    confidence_scores: Dict[str, float] = result.get("confidence_scores", {})
    avg_confidence = (
        sum(confidence_scores.values()) / len(confidence_scores)
        if confidence_scores else 0.0
    )
    logger.info(
        "AI re-rank reasoning: %s | avg_confidence=%.2f",
        result.get("reasoning", ""),
        avg_confidence,
    )

    title_map: Dict[str, Tuple[Dict, float, str]] = {
        s["title"]: (s, score, expl) for s, score, expl in candidates
    }

    reranked: List[Tuple[Dict, float, str]] = []
    seen_titles: set = set()
    for title in result.get("ranked_titles", []):
        if title in title_map and title not in seen_titles:
            reranked.append(title_map[title])
            seen_titles.add(title)
        else:
            logger.warning("AI returned unknown or duplicate title %r — skipping", title)

    for title, tup in title_map.items():
        if title not in seen_titles:
            logger.warning("AI omitted %r — appending at end", title)
            reranked.append(tup)

    return reranked, confidence_scores


class AIRecommender:
    """Orchestrates the two-stage NL-parse → weighted-score → AI-rerank pipeline."""

    def __init__(self, songs: List[Dict]):
        self.songs = songs
        self.client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

    def recommend(
        self, user_description: str, k: int = 5
    ) -> Tuple[List[Tuple[Dict, float, str]], Optional[Dict], bool, Dict[str, float]]:
        """Run the full AI pipeline.

        Returns (top_k_results, parsed_profile, fallback_used, confidence_scores).
        Falls back to pure weighted scorer on any API or JSON error.
        """
        try:
            profile = parse_natural_language(user_description, self.client)
            candidates = recommend_songs(profile, self.songs, k=10)
            reranked, confidence_scores = ai_rerank(user_description, candidates, self.client)
            return reranked[:k], profile, False, confidence_scores

        except (APIError, json.JSONDecodeError, KeyError) as exc:
            logger.warning(
                "AI pipeline failed (%s: %s) — falling back to weighted scorer",
                type(exc).__name__,
                exc,
            )
            fallback_profile = _keyword_fallback(user_description)
            results = recommend_songs(fallback_profile, self.songs, k=k)
            return results, None, True, {}


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

    energy = 0.5
    if any(w in text_lower for w in ("workout", "gym", "energy", "hype", "intense", "pump")):
        energy = 0.85
    elif any(w in text_lower for w in ("chill", "relax", "study", "focus", "calm", "sleep")):
        energy = 0.35

    mood = "happy"
    for kw, m in [
        ("sad", "melancholy"), ("melancholy", "melancholy"), ("chill", "chill"),
        ("study", "focused"), ("focus", "focused"), ("intense", "intense"),
        ("romantic", "romantic"), ("peaceful", "peaceful"),
    ]:
        if kw in text_lower:
            mood = m
            break

    return {"genre": genre, "mood": mood, "energy": energy, "valence": 0.6, "tempo_bpm": 100}
