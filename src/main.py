"""
Command-line runner for the Music Recommender Simulation.
Run from the project root: python -m src.main

Modes
-----
classic (default)
    Runs all five predefined profiles plus the weight-experiment block.
    No API key required.

ai
    Accepts a natural-language query, parses it into a structured profile
    via Claude, runs the weighted scorer to get candidates, then lets Claude
    re-rank them.  Requires ANTHROPIC_API_KEY in the environment (.env file).

Usage examples
--------------
    python -m src.main
    python -m src.main --mode classic
    python -m src.main --mode ai --query "something chill for late-night studying"
    python -m src.main --mode ai --query "pump-up gym playlist, maximum energy"
"""

import argparse
import os
import sys

from dotenv import load_dotenv

from recommender import load_songs, recommend_songs, DEFAULT_WEIGHTS

load_dotenv()  # load ANTHROPIC_API_KEY from .env if present

BAR = "─" * 60

# ---------------------------------------------------------------------------
# User Profiles
# ---------------------------------------------------------------------------

PROFILES = {
    "High-Energy Pop Fan": {
        "genre":     "pop",
        "mood":      "happy",
        "energy":    0.90,
        "valence":   0.85,
        "tempo_bpm": 128,
    },
    "Chill Lofi Studier": {
        "genre":     "lofi",
        "mood":      "chill",
        "energy":    0.38,
        "valence":   0.60,
        "tempo_bpm": 78,
    },
    "Deep Intense Rock": {
        "genre":     "rock",
        "mood":      "intense",
        "energy":    0.95,
        "valence":   0.40,
        "tempo_bpm": 155,
    },
    # Edge case: conflicting preferences (high energy + melancholy mood)
    # Tests whether numerical features can override categorical mismatch
    "Conflicted Raver (edge case)": {
        "genre":     "edm",
        "mood":      "melancholy",
        "energy":    0.95,
        "valence":   0.25,
        "tempo_bpm": 140,
    },
    # Edge case: niche genre with only one match in the catalog
    "Classical Explorer (edge case)": {
        "genre":     "classical",
        "mood":      "peaceful",
        "energy":    0.20,
        "valence":   0.75,
        "tempo_bpm": 65,
    },
}

# ---------------------------------------------------------------------------
# Experiment: double energy weight, halve genre weight
# This tests whether energy can drive recommendations more than genre loyalty.
# ---------------------------------------------------------------------------
EXPERIMENTAL_WEIGHTS = {
    **DEFAULT_WEIGHTS,
    "genre":  1.0,   # halved from 2.0
    "energy": 4.0,   # doubled from 2.0
}


def print_recommendations(label: str, prefs: dict, songs: list, weights=None) -> None:
    """Print a formatted recommendation block for one user profile."""
    print(f"\n{BAR}")
    print(f"  PROFILE: {label}")
    print(f"  genre={prefs.get('genre')}  mood={prefs.get('mood')}  "
          f"energy={prefs.get('energy')}  valence={prefs.get('valence', '—')}")
    if weights:
        print(f"  [EXPERIMENTAL weights: genre={weights['genre']}, energy={weights['energy']}]")
    print(BAR)

    results = recommend_songs(prefs, songs, k=5, weights=weights)
    for rank, (song, score, explanation) in enumerate(results, start=1):
        print(f"  {rank}. {song['title']}  —  {song['artist']}")
        print(f"     Genre: {song['genre']:<14} Mood: {song['mood']:<14} Score: {score:.2f}")
        print(f"     Why: {explanation}")
    print()


def run_classic_mode(songs: list) -> None:
    """Run all predefined profiles plus the weight-experiment block."""
    for label, prefs in PROFILES.items():
        print_recommendations(label, prefs, songs)

    print(f"\n{'═' * 60}")
    print("  EXPERIMENT: doubled energy weight, halved genre weight")
    print(f"  (applied to 'High-Energy Pop Fan' profile)")
    print(f"{'═' * 60}")
    print_recommendations(
        "High-Energy Pop Fan [EXPERIMENTAL]",
        PROFILES["High-Energy Pop Fan"],
        songs,
        weights=EXPERIMENTAL_WEIGHTS,
    )


def run_ai_mode(query: str, songs: list) -> None:
    """Run the two-stage AI pipeline for a natural-language query."""
    # Import here so classic mode never requires the anthropic package
    from ai_recommender import AIRecommender

    if not os.environ.get("ANTHROPIC_API_KEY"):
        print(
            "ERROR: ANTHROPIC_API_KEY is not set.\n"
            "Add it to a .env file or export it in your shell:\n"
            "  export ANTHROPIC_API_KEY=sk-ant-...",
            file=sys.stderr,
        )
        sys.exit(1)

    print(f"\n{'═' * 60}")
    print("  VibeFinder — AI Mode")
    print(f"  Query: \"{query}\"")
    print(f"{'═' * 60}")

    rec = AIRecommender(songs)
    results, profile, fallback_used = rec.recommend(query, k=5)

    if fallback_used:
        print("  [AI unavailable — showing weighted-scorer results]\n")
    else:
        print(f"\n  Parsed profile:")
        print(f"    genre={profile.get('genre')}  mood={profile.get('mood')}  "
              f"energy={profile.get('energy')}  valence={profile.get('valence')}  "
              f"tempo={profile.get('tempo_bpm')} bpm")
        print(f"\n  AI-ranked recommendations:")

    print(f"\n{BAR}")
    for rank, (song, score, explanation) in enumerate(results, start=1):
        print(f"  {rank}. {song['title']}  —  {song['artist']}")
        print(f"     Genre: {song['genre']:<14} Mood: {song['mood']:<14} Score: {score:.2f}")
        print(f"     Why: {explanation}")
    print()


def main() -> None:
    parser = argparse.ArgumentParser(
        description="VibeFinder Music Recommender",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--mode",
        choices=["classic", "ai"],
        default="classic",
        help="classic: run all predefined profiles (default); ai: natural-language query",
    )
    parser.add_argument(
        "--query",
        type=str,
        default=None,
        help="Natural-language preference description (required for --mode ai)",
    )
    args = parser.parse_args()

    if args.mode == "ai" and not args.query:
        parser.error("--query is required when using --mode ai")

    songs = load_songs("data/songs.csv")
    print(f"\nLoaded {len(songs)} songs from catalog.\n")

    if args.mode == "ai":
        run_ai_mode(args.query, songs)
    else:
        run_classic_mode(songs)


if __name__ == "__main__":
    main()
