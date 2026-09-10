# Grok GTM Agent

Give Grok a product. It finds companies with a reason to buy it **right now**.

CLI research agent that turns a short product description into **five evidence-backed B2B opportunities** — with buying signals, explainable scores, and personalized outreach. No website. No database. Terminal + JSON.

## What it does

```
PRODUCT
→ ICP
→ COMPANY DISCOVERY
→ WEB + X RESEARCH
→ BUYING SIGNALS
→ SCORING
→ TOP 5
→ WHY NOW
→ OUTREACH
```

Grok discovers and researches real companies (xAI `web_search` + `x_search` in live mode). A local, explainable scoring layer ranks opportunities — the final GTM score is derived from components, not invented as a single opaque LLM number.

## Demo

A screen-recording-ready visual showcase lives in [`video_demo/`](video_demo/). Open `video_demo/index.html` (or serve that folder) to play the autoplay loop built from a real LIVE hero run.

```bash
cd video_demo
python3 -m http.server 8765
# open http://127.0.0.1:8765/
```

## Features

- Automatic ICP generation
- Real company discovery
- Web research + X research (live mode)
- Evidence-backed buying signals (no invented URLs)
- Freshness weighting
- Explainable GTM scoring
- Top 5 ranking
- WHY NOW reasoning
- Personalized outreach
- Structured JSON output
- Demo + live modes

## How it works

| Layer | Role |
|-------|------|
| **Grok (xAI)** | ICP, discovery, tool-augmented research, outreach copy |
| **`scoring.py`** | Local component scores → GTM SCORE 0–100 |
| **`research.py`** | Demo dataset loader **or** live research orchestration |
| **`main.py`** | CLI + progressive terminal UI |

**Demo mode** loads deterministic data from `demo/` and runs real scoring — no API key.  
**Live mode** requires `XAI_API_KEY` and never falls back to demo data on failure.

## Installation

```bash
git clone https://github.com/deilymoon/grok-gtm-agent.git
cd grok-gtm-agent
python3 -m venv .venv
source .venv/bin/activate   # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

## Configuration

```bash
cp .env.example .env
```

| Variable | Description |
|----------|-------------|
| `XAI_API_KEY` | xAI API key (required for `--mode live`) |
| `MODE` | `demo` (default) or `live` |
| `MODEL` | Grok model id (default `grok-4-1-fast-reasoning`) |
| `RESEARCH_LIMIT` | Max candidates to research in live mode |

Never commit `.env`. Never put a real key in this README.

## Run demo

```bash
python main.py --mode demo
# or:
python main.py --mode demo "AI tool that automates customer support research for B2B SaaS companies."
```

## Run live

```bash
python main.py --mode live "AI platform for B2B SaaS support teams"
# or:
python main.py --mode live --product "AI platform for B2B SaaS support teams"
```

Useful flags: `--limit`, `--output`, `--verbose`, `--no-hold`.

## Example result

Illustrative shape (see also [`examples/example_leads.json`](examples/example_leads.json)):

```
Example Analytics Co                         87/100

SIGNALS
  ✓ hiring: Expanding customer support / success roles
  ✓ product_launch: New AI-assisted workflows
  ✓ growth: Rapid customer growth

WHY NOW
  Support hiring + product expansion → rising research load on CX teams.

BEST CONTACT
  Head of Customer Support

OUTREACH
  Short personalized note referencing those signals…
```

## Scoring

Weighted components (sum to 1.0):

| Component | Weight |
|-----------|--------|
| ICP Fit | 0.25 |
| Signal Strength | 0.20 |
| Signal Freshness | 0.15 |
| Problem Relevance | 0.15 |
| Timing | 0.15 |
| Evidence Confidence | 0.10 |

Fresh signals (especially 0–30 / 31–90 days) weigh more than stale events. Companies without meaningful evidence are discarded in live mode.

## Output

Runtime artifacts (gitignored under `output/`):

- `output/leads.json` — latest top opportunities
- `output/runs/<timestamp>.json` — timestamped full run snapshot

## Tests

```bash
pytest
```

Covers scoring, models/validation, freshness, URL sanitization, and ranking helpers.

## Project layout

```
main.py          CLI + Rich UI
agent.py         Pipeline orchestration
research.py      Demo loader + live research
scoring.py       Explainable GTM scores
models.py        Pydantic models
prompts.py       Grok prompt templates
config.py        Env / mode loading
xai_client.py    xAI chat + Responses tools client
url_utils.py     Source URL validation
demo/            Deterministic demo dataset
tests/           pytest suite
video_demo/      Visual product showcase
examples/        Sample output schema
```

## Disclaimer

This tool uses **public** information for GTM research assistance. Always verify evidence and comply with applicable laws and platform terms before contacting companies. Scores are decision support — not guarantees of purchase intent.

## License

MIT — see [LICENSE](LICENSE).
