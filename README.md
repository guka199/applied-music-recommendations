# VibeFinder — AI-Powered Music Recommender

> A content-based music recommender extended with a Claude-powered natural-language pipeline.
> Built as a portfolio project demonstrating end-to-end AI system design: scoring logic,
> LLM integration, guardrails, fallback architecture, and automated testing.

---

## Original Project (Modules 1–3)

The foundation of this project is the **Music Recommender Simulation** built during Modules 1–3
of the AI 110 course. Its original goal was to model how content-based recommender systems work
by representing songs as five numeric/categorical features and scoring them against a user's
stated taste profile using a weighted proximity formula. It demonstrated that even a simple
mathematical scorecard — applied to the right features — can produce surprisingly plausible
recommendations, and it surfaced real biases (genre-count skew, coarse mood vocabulary) that
exist in production systems at scale.

---

## What VibeFinder AI Does and Why It Matters

VibeFinder AI extends the original scorecard with a two-stage Claude pipeline:

1. **Natural language → structured profile.** A user can type _"something melancholy and slow for
   a rainy afternoon"_ instead of manually entering `energy=0.25, valence=0.30, tempo_bpm=72`.
   Claude parses the intent and produces the structured profile the weighted scorer needs.

2. **AI re-ranking.** After the weighted scorer returns its top-10 candidates, Claude applies
   musical domain knowledge to re-order them — catching nuances the formula misses (e.g.,
   "this user said *late-night*, so the moody synthwave track should rank above the upbeat indie
   pop even though both scored similarly").

The result is a system that is **transparent** (every score is explainable), **reliable**
(falls back to pure weighted scoring if the API is unavailable), and **testable** (all AI
calls are mockable; 6 automated tests cover correctness, guardrails, and consistency).

This matters because it demonstrates the core challenge of applied AI: not just calling an LLM,
but integrating it safely into a larger system with clear failure modes, output validation, and
a fallback path.

---

## Architecture Overview

```
USER INPUT
│
├── Classic mode ──────────────────────────────────────────────────────┐
│   (predefined profiles: genre, mood, energy, valence, tempo_bpm)     │
│                                                                       │
└── AI mode (natural-language query) ──────────────────────────────────┤
    │                                                                   │
    ▼                                                                   │
┌────────────────────────────┐                                         │
│  Stage 1: NL Parser        │  src/ai_recommender.py                  │
│  claude-opus-4-7           │  JSON schema enforcement                 │
│  → {genre, mood, energy,   │  Cache-control annotated for growth      │
│     valence, tempo_bpm}    │                                          │
└─────────────┬──────────────┘                                         │
              │ structured profile                                      │
              ▼                                                         ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    Weighted Scorer  (src/recommender.py)                │
│                                                                         │
│  score = genre_match×2.0 + mood_match×1.0 + energy_prox×2.0            │
│        + valence_prox×1.5 + tempo_prox×1.0                             │
│  → sorted (song, score, explanation) pairs                              │
└─────────────┬───────────────────────────────────────┬──────────────────┘
              │ AI mode: top-10                Classic mode: top-5 → OUTPUT
              ▼
┌────────────────────────────┐       HUMAN / TEST CHECKPOINTS
│  Stage 3: AI Re-ranker     │  ←──  ① Guardrail: hallucinated titles
│  claude-opus-4-7           │         filtered before output
│  Musical domain reasoning  │  ←──  ② Fallback test: APIError →
│  JSON schema output        │         weighted scorer used instead
└─────────────┬──────────────┘  ←──  ③ Consistency test: same mock
              │ top-5               → same top result
              ▼               ←──  ④ Logs: every Claude call
         FINAL OUTPUT               recorded to logs/YYYY-MM-DD.log

FALLBACK PATH (any anthropic.APIError or JSON decode error)
  → keyword heuristic profile → weighted scorer top-5 → labeled [AI unavailable]
```

The weighted scorer is the **reliable backbone** — it runs in both modes and is the safety
net when the AI layer fails. The two Claude stages wrap it like middleware: they improve
quality when available but never become a single point of failure.

---

## Setup Instructions

### Prerequisites

- Python 3.9+
- An Anthropic API key (only required for `--mode ai`)

### 1. Clone the repository

```bash
git clone https://github.com/guka199/applied-music-recommendations.git
cd applied-music-recommendations
```

### 2. Create and activate a virtual environment (recommended)

```bash
python -m venv .venv
source .venv/bin/activate      # Mac / Linux
.venv\Scripts\activate         # Windows
```

### 3. Install dependencies

```bash
pip install -r requirements.txt
```

### 4. Configure your API key (AI mode only)

```bash
cp .env.example .env
# Open .env and replace the placeholder with your real key:
# ANTHROPIC_API_KEY=sk-ant-...
```

Get a key at <https://console.anthropic.com>.

### 5. Run the app

**Classic mode** (no API key needed — runs all five predefined profiles):

```bash
python -m src.main
```

**AI mode** (natural-language query):

```bash
python -m src.main --mode ai --query "something chill for late-night studying"
python -m src.main --mode ai --query "maximum energy gym playlist"
python -m src.main --mode ai --query "melancholy rainy day, slow and acoustic"
```

### 6. Run the tests

```bash
pytest
```

All 6 tests run without an API key (Anthropic calls are mocked).

---

## Sample Interactions

### Classic mode — Chill Lofi Studier

```
Loaded 18 songs from catalog.

────────────────────────────────────────────────────────────
  PROFILE: Chill Lofi Studier
  genre=lofi  mood=chill  energy=0.38  valence=0.6
────────────────────────────────────────────────────────────
  1. Library Rain  —  Paper Lanterns
     Genre: lofi           Mood: chill          Score: 7.41
     Why: genre match (+2.0); mood match (+1.0); energy proximity (+1.90); ...

  2. Midnight Coding  —  LoRoom
     Genre: lofi           Mood: chill          Score: 7.36
     Why: genre match (+2.0); mood match (+1.0); energy proximity (+1.96); ...

  3. Focus Flow  —  LoRoom
     Genre: lofi           Mood: focused        Score: 6.44
     Why: genre match (+2.0); energy proximity (+2.00); valence proximity (+1.49); ...
```

Both top slots are the most textbook-lofi tracks in the catalog — exactly what a human
DJ would choose.

---

### AI mode — "late-night melancholy, something slow"

```
Loaded 18 songs from catalog.

════════════════════════════════════════════════════════════
  VibeFinder — AI Mode
  Query: "late-night melancholy, something slow"
════════════════════════════════════════════════════════════

  Parsed profile:
    genre=blues  mood=melancholy  energy=0.28  valence=0.30  tempo=72 bpm

  AI-ranked recommendations:

────────────────────────────────────────────────────────────
  1. Crossroads Lament  —  Blue Delta
     Genre: blues          Mood: melancholy     Score: 5.84
     Why: genre match (+2.0); mood match (+1.0); energy proximity (+1.96); ...

  2. Library Rain  —  Paper Lanterns
     Genre: lofi           Mood: chill          Score: 4.21
     Why: energy proximity (+1.90); valence proximity (+1.35); ...

  3. Spacewalk Thoughts  —  Orbit Bloom
     Genre: ambient        Mood: chill          Score: 3.99
     Why: energy proximity (+1.96); tempo proximity (+0.84); ...
```

Claude correctly identified "melancholy" + "slow" as a blues/low-energy profile and
surfaced Crossroads Lament — the only blues track in the catalog — at rank 1. The pure
weighted scorer would have buried it behind higher-energy genre matches.

---

### AI mode — "pump-up gym playlist, maximum energy"

```
════════════════════════════════════════════════════════════
  VibeFinder — AI Mode
  Query: "pump-up gym playlist, maximum energy"
════════════════════════════════════════════════════════════

  Parsed profile:
    genre=edm  mood=euphoric  energy=0.97  valence=0.85  tempo=145 bpm

  AI-ranked recommendations:

────────────────────────────────────────────────────────────
  1. Ultraviolet Drop  —  Bassline Theory
     Genre: edm            Mood: euphoric       Score: 7.42
     Why: genre match (+2.0); mood match (+1.0); energy proximity (+1.96); ...

  2. Gym Hero  —  Max Pulse
     Genre: pop            Mood: intense        Score: 5.81
     Why: energy proximity (+1.92); valence proximity (+1.43); ...

  3. Iron Storm  —  Rageform
     Genre: metal          Mood: aggressive     Score: 4.12
     Why: energy proximity (+1.82); tempo proximity (+0.82); ...
```

---

### Fallback mode (API unavailable)

```
WARNING: AI pipeline failed (APIError: rate limit) — falling back to weighted scorer

════════════════════════════════════════════════════════════
  VibeFinder — AI Mode
  Query: "pump-up gym playlist, maximum energy"
════════════════════════════════════════════════════════════
  [AI unavailable — showing weighted-scorer results]
```

The system degrades gracefully — the user still gets recommendations; they are just not
Claude-re-ranked.

---

## Design Decisions

### Why a two-stage pipeline instead of asking Claude to pick songs directly?

Letting Claude choose songs directly from a free-text query would be simpler to build but
harder to control. Claude could hallucinate song titles, ignore catalog constraints, or
produce inconsistent results between calls. The weighted scorer acts as a ground-truth filter:
Claude only re-orders songs that actually exist in the catalog, and the guardrail in
`ai_rerank()` drops any title the AI invents. This pattern — *LLM as a ranker over a
controlled candidate set* — is how production search and recommendation systems use LLMs
safely (Google MusicLM, Spotify AI DJ).

### Why structured JSON output (`output_config.format`) instead of parsing free text?

Prompt-engineering Claude to always output valid JSON is fragile. The `output_config` with
a `json_schema` field enforces the schema at the API level, eliminating the entire class of
bugs where Claude adds an explanation sentence or wraps the JSON in a code block. The tradeoff
is slightly higher token overhead for the schema declaration — worth it for reliability.

### Why keep the weighted scorer at all?

Two reasons. First, it is the fallback when the API is unavailable. Second, it forces a
structured representation of user preferences: before Claude can re-rank, the NL parser
must produce a profile the scorer can consume. This two-pass design means the system always
knows *why* a song scored well (the formula) even if Claude's re-ranking changes the order.

### Why `cache_control: ephemeral` on the system prompt?

The system prompt is stable across all requests in a session. Marking it with
`cache_control: {"type": "ephemeral"}` tells the Anthropic API to cache that prefix, reducing
latency and token cost for repeated calls. The 18-song catalog is currently too small to hit
the 4096-token minimum for caching to activate, but the annotation is in place so caching
kicks in automatically as the catalog grows — no code change needed.

### Trade-offs

| Decision | Benefit | Cost |
|---|---|---|
| Two-stage pipeline | Guardrailed, explainable | Two API calls per query |
| JSON schema enforcement | No parsing fragility | Slightly more tokens |
| Weighted scorer fallback | 100% uptime | Fallback quality lower than AI mode |
| File + console logging | Full audit trail | Log files accumulate |
| Keyword heuristic fallback profile | Works with no API | Coarser than Claude's parse |

---

## Testing Summary

**7 out of 7 tests passed** in 0.28 seconds. All Anthropic API calls are mocked — no API key
required to run the test suite.

```
tests/test_ai_recommender.py::test_parse_nl_validates_required_keys      PASSED
tests/test_ai_recommender.py::test_ai_rerank_only_returns_catalog_songs  PASSED
tests/test_ai_recommender.py::test_ai_rerank_confidence_scores_returned  PASSED
tests/test_ai_recommender.py::test_ai_fallback_on_api_error              PASSED
tests/test_ai_recommender.py::test_ai_recommender_consistency            PASSED
tests/test_recommender.py::test_recommend_returns_songs_sorted_by_score  PASSED
tests/test_recommender.py::test_explain_recommendation_returns_non_empty_string PASSED

7 passed in 0.28s
```

### Four reliability mechanisms

**1. Automated tests** — 7 pytest tests covering the weighted scorer, NL parser, output
guardrail, API fallback, confidence score extraction, and result consistency. All AI calls
are replaced with `unittest.mock.MagicMock` so tests are deterministic and free to run.

**2. Confidence scoring** — Claude self-reports a match confidence (0.0–1.0) for each
re-ranked song. These are validated in `test_ai_rerank_confidence_scores_returned` and
displayed in the CLI:

```
  Parsed profile:
    genre=blues  mood=melancholy  energy=0.28  valence=0.30  tempo=72 bpm
    AI avg confidence across top results: 0.81

  1. Crossroads Lament  —  Blue Delta  [AI confidence: 0.94]
  2. Library Rain  —  Paper Lanterns   [AI confidence: 0.72]
  3. Spacewalk Thoughts  —  Orbit Bloom [AI confidence: 0.65]
```

A low average confidence (below ~0.6) signals that the catalog doesn't contain a strong
match for the query — useful feedback even without a numeric accuracy metric.

**3. Logging and error handling** — every AI call is recorded to `logs/YYYY-MM-DD.log`
at DEBUG level. Guardrail events (hallucinated titles, omitted songs, API failures) are
logged at WARNING so they stand out in the file. Sample from a real test run:

```
2026-04-27 00:11:35  DEBUG    vibefinder.ai  parse_natural_language called with input: 'something chill for studying'
2026-04-27 00:11:35  INFO     vibefinder.ai  Parsed profile: {'genre': 'lofi', 'mood': 'chill', 'energy': 0.38, ...}
2026-04-27 00:11:35  DEBUG    vibefinder.ai  ai_rerank called with 3 candidates
2026-04-27 00:11:35  INFO     vibefinder.ai  AI re-rank reasoning: ... | avg_confidence=0.79
2026-04-27 00:11:35  WARNING  vibefinder.ai  AI returned unknown or duplicate title 'HALLUCINATED TRACK' — skipping
2026-04-27 00:11:35  WARNING  vibefinder.ai  AI pipeline failed (APIError: rate limit) — falling back to weighted scorer
```

**4. Human evaluation** — five user profiles were tested manually (see Sample Interactions).
The system correctly placed the expected top song for 4 out of 5 profiles. The one imperfect
case was the "Conflicted Raver" edge case (high-energy EDM + melancholy mood), where the
genre bonus overrides the mood signal — a known bias documented in the model card.

### What worked

- The guardrail test caught a real design gap during development: what happens when Claude
  returns a title that doesn't exist in the catalog? The safety-net append (omitted songs
  appended at the end) was the right answer — the user always gets a full top-5.
- The fallback test was straightforward because `anthropic.APIError` is a real importable
  exception class in the SDK, not a string to pattern-match against.
- Confidence scores turned out to be a lightweight proxy for "how well does the catalog
  serve this query?" — low scores for niche genres (classical, blues) reflect real catalog
  depth limitations, not a bug in the model.

### What didn't work initially

- The first version of `AIRecommender.recommend()` had a leftover line calling the weighted
  scorer with the raw query string instead of the parsed profile dict. This caused an
  `AttributeError` on `score_song()`. Caught immediately by `test_ai_recommender_consistency`.
- Prompt caching (`cache_control: ephemeral`) does not activate on the 18-song catalog —
  the prefix is below the 4096-token minimum. The annotation stays in the code as a
  forward-looking optimization for catalog growth.

### What I learned

Testing an LLM-integrated system means testing the *plumbing*, not the AI. You mock the
model and verify that your code handles valid output, malformed output (guardrail), and
failure (fallback) correctly. The AI's actual quality is evaluated through sample
interactions and confidence scores — automated tests guarantee safety; confidence scores
quantify fit.

---

## Reflection

### What this project taught me about AI

Building VibeFinder in two versions — first without AI, then with — made one thing concrete:
**the AI layer is not the intelligence; the system design is**. The weighted scorer was already
producing surprisingly good recommendations. Claude's value was not replacing that logic but
making it accessible (natural language in) and making it more nuanced (musical reasoning at
the ranking step). Real production AI systems work this way: an LLM sits on top of
deterministic retrieval and scoring, not instead of it.

### The alignment moment

The "Conflicted Raver" edge case from the original project — a profile with EDM genre but
melancholy mood — exposed the core tension in any recommender: when the user's own preferences
contradict each other, whose priority wins? The formula answers "genre + energy" because that's
what the weights say. Claude, given the same user description, correctly picks up the emotional
subtext: someone asking for "high-energy but melancholy" probably wants something that *sounds*
intense but *feels* introspective — a better answer than what the formula produces. That gap
between "correct by the formula" and "right for the human" is where AI alignment lives, even in
a music app.

### What I'd build next

1. **Genre similarity graph** — replace the binary genre bonus with a distance matrix so
   "indie pop" and "pop" share partial credit, reducing the catalog-skew bias.
2. **Implicit feedback loop** — track which recommendations the user skips vs. replays and
   nudge target values between sessions, turning VibeFinder from a static form into a system
   that actually learns.
3. **Diversity enforcement** — cap results at one song per artist to prevent catalog depth
   from letting one artist sweep all five slots.

---

## Project Structure

```
applied-music-recommendations/
├── data/
│   └── songs.csv               # 18-song catalog (genre, mood, energy, valence, tempo, …)
├── src/
│   ├── recommender.py          # Core weighted scorer — load_songs, score_song, recommend_songs
│   ├── ai_recommender.py       # Claude integration — NL parser, re-ranker, AIRecommender class
│   ├── logger.py               # Centralized logging (file DEBUG + console WARNING)
│   └── main.py                 # CLI entry point (--mode classic|ai  --query TEXT)
├── tests/
│   ├── conftest.py             # sys.path setup for pytest
│   ├── test_recommender.py     # Core scorer tests
│   └── test_ai_recommender.py  # AI layer tests (all calls mocked)
├── logs/                       # Auto-created; YYYY-MM-DD.log written at runtime
├── model_card.md               # VibeFinder model card (intended use, bias, evaluation)
├── .env.example                # API key template — copy to .env
├── .gitignore
└── requirements.txt
```

---

## Tech Stack

| Layer | Technology |
|---|---|
| Language | Python 3.9+ |
| AI model | Claude Opus 4.7 (`claude-opus-4-7`) via Anthropic SDK |
| Structured output | `output_config.format` with `json_schema` |
| Prompt caching | `cache_control: ephemeral` on system prompt |
| Environment config | `python-dotenv` |
| Testing | `pytest` + `unittest.mock` |
| Logging | Python `logging` (file + console handlers) |
| Data | CSV catalog, 18 songs, 10 audio features |
