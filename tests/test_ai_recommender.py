"""
Unit tests for the AI recommendation layer.

All Groq API calls are mocked — no network access or API key required.
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from src.ai_recommender import AIRecommender, ai_rerank, parse_natural_language

SAMPLE_SONGS = [
    {"id": 1, "title": "Sunrise City", "artist": "Neon Echo",
     "genre": "pop", "mood": "happy",
     "energy": 0.82, "tempo_bpm": 118, "valence": 0.84,
     "danceability": 0.79, "acousticness": 0.18},
    {"id": 2, "title": "Midnight Coding", "artist": "LoRoom",
     "genre": "lofi", "mood": "chill",
     "energy": 0.42, "tempo_bpm": 78, "valence": 0.56,
     "danceability": 0.62, "acousticness": 0.71},
    {"id": 3, "title": "Storm Runner", "artist": "Voltline",
     "genre": "rock", "mood": "intense",
     "energy": 0.91, "tempo_bpm": 152, "valence": 0.48,
     "danceability": 0.66, "acousticness": 0.10},
    {"id": 4, "title": "Library Rain", "artist": "Paper Lanterns",
     "genre": "lofi", "mood": "chill",
     "energy": 0.35, "tempo_bpm": 72, "valence": 0.60,
     "danceability": 0.58, "acousticness": 0.86},
    {"id": 5, "title": "Gym Hero", "artist": "Max Pulse",
     "genre": "pop", "mood": "intense",
     "energy": 0.93, "tempo_bpm": 132, "valence": 0.77,
     "danceability": 0.88, "acousticness": 0.05},
]


def _mock_groq_response(text: str) -> MagicMock:
    """Build a minimal mock that looks like a Groq chat completion response."""
    message = MagicMock()
    message.content = text
    choice = MagicMock()
    choice.message = message
    response = MagicMock()
    response.choices = [choice]
    return response


def _rerank_json(ranked_titles, confidence_scores=None, reasoning="Test reasoning."):
    if confidence_scores is None:
        confidence_scores = {t: 0.8 for t in ranked_titles}
    return json.dumps({
        "ranked_titles": ranked_titles,
        "confidence_scores": confidence_scores,
        "reasoning": reasoning,
    })


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_parse_nl_validates_required_keys():
    """parse_natural_language must return a dict with all five required keys."""
    profile_json = json.dumps({
        "genre": "lofi", "mood": "chill",
        "energy": 0.38, "valence": 0.60, "tempo_bpm": 78,
    })
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_groq_response(profile_json)

    result = parse_natural_language("something chill for studying", client)

    required = {"genre", "mood", "energy", "valence", "tempo_bpm"}
    assert required.issubset(result.keys()), f"Missing keys: {required - result.keys()}"
    assert result["genre"] == "lofi"
    assert result["mood"] == "chill"


def test_ai_rerank_only_returns_catalog_songs():
    """ai_rerank must silently drop any title the AI invents that is not in the catalog."""
    candidates = [
        (SAMPLE_SONGS[0], 7.0, "energy proximity"),
        (SAMPLE_SONGS[1], 6.5, "genre match"),
        (SAMPLE_SONGS[2], 5.8, "mood match"),
    ]
    response_json = _rerank_json(
        ranked_titles=["Sunrise City", "HALLUCINATED TRACK", "Midnight Coding"],
        confidence_scores={"Sunrise City": 0.92, "HALLUCINATED TRACK": 0.75, "Midnight Coding": 0.65},
    )
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_groq_response(response_json)

    reranked, confidence_scores = ai_rerank("chill evening vibes", candidates, client)

    returned_titles = [s["title"] for s, _, _ in reranked]
    assert "HALLUCINATED TRACK" not in returned_titles
    assert "Sunrise City" in returned_titles
    assert "Midnight Coding" in returned_titles
    assert "Storm Runner" in returned_titles
    assert confidence_scores["Sunrise City"] == pytest.approx(0.92)


def test_ai_rerank_confidence_scores_returned():
    """ai_rerank must return the confidence_scores dict from the AI response."""
    candidates = [
        (SAMPLE_SONGS[0], 7.0, "energy proximity"),
        (SAMPLE_SONGS[1], 6.5, "genre match"),
    ]
    response_json = _rerank_json(
        ranked_titles=["Sunrise City", "Midnight Coding"],
        confidence_scores={"Sunrise City": 0.95, "Midnight Coding": 0.70},
    )
    client = MagicMock()
    client.chat.completions.create.return_value = _mock_groq_response(response_json)

    _, confidence_scores = ai_rerank("happy upbeat vibes", candidates, client)

    assert confidence_scores["Sunrise City"] == pytest.approx(0.95)
    assert confidence_scores["Midnight Coding"] == pytest.approx(0.70)
    avg = sum(confidence_scores.values()) / len(confidence_scores)
    assert avg == pytest.approx(0.825)


def test_ai_fallback_on_api_error():
    """AIRecommender must fall back to the weighted scorer when the API raises APIError."""
    from groq import APIError

    with patch("src.ai_recommender.Groq") as MockGroq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = APIError(
            message="rate limit", request=MagicMock(), body={}
        )
        MockGroq.return_value = mock_client

        rec = AIRecommender(SAMPLE_SONGS)
        results, profile, fallback_used, confidence_scores = rec.recommend(
            "energetic workout music", k=3
        )

    assert fallback_used is True
    assert profile is None
    assert confidence_scores == {}
    assert len(results) == 3
    for song, score, explanation in results:
        assert "title" in song
        assert isinstance(score, float)


def test_ai_recommender_consistency():
    """Same mock response must produce the same top recommendation every run."""
    profile_json = json.dumps({
        "genre": "pop", "mood": "happy",
        "energy": 0.90, "valence": 0.85, "tempo_bpm": 128,
    })
    rerank_response = _rerank_json(
        ranked_titles=["Gym Hero", "Sunrise City", "Storm Runner", "Library Rain", "Midnight Coding"],
        confidence_scores={
            "Gym Hero": 0.91, "Sunrise City": 0.85, "Storm Runner": 0.72,
            "Library Rain": 0.45, "Midnight Coding": 0.40,
        },
        reasoning="Gym Hero's intensity matches best.",
    )

    def _make_side_effect(profile_json, rerank_response):
        state = {"count": 0}
        def _side_effect(*args, **kwargs):
            state["count"] += 1
            return _mock_groq_response(
                profile_json if state["count"] == 1 else rerank_response
            )
        return _side_effect

    with patch("src.ai_recommender.Groq") as MockGroq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = _make_side_effect(
            profile_json, rerank_response
        )
        MockGroq.return_value = mock_client
        rec = AIRecommender(SAMPLE_SONGS)
        results1, _, _, conf1 = rec.recommend("high energy pop workout")

    with patch("src.ai_recommender.Groq") as MockGroq:
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = _make_side_effect(
            profile_json, rerank_response
        )
        MockGroq.return_value = mock_client
        rec2 = AIRecommender(SAMPLE_SONGS)
        results2, _, _, conf2 = rec2.recommend("high energy pop workout")

    assert results1[0][0]["title"] == results2[0][0]["title"]
    assert conf1 == conf2
