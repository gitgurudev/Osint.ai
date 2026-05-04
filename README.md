# OSINT AI — Digital Intelligence Engine

A real-time public digital footprint analyzer. Enter a name or username and get a structured intelligence report — profiles found, identity clusters, ranked sources, and AI-generated insights — in seconds.

## Pipeline

```
Search (DuckDuckGo) → Scrape Pages → Rule-based Analysis → GPT-4o Enhancement
```

All stages stream live progress to the browser via Server-Sent Events (SSE).

## Features

- **Real-time SSE pipeline** — watch each stage complete in the browser as it happens
- **DuckDuckGo search** — no API key required for search
- **Page scraper** — extracts content from discovered URLs
- **Rule-based analysis** — entity clustering, profile detection, credibility scoring
- **GPT-4o enhancement** — optional AI summary and deeper insights (requires OpenAI key)
- **Rate limiting** — 5 requests per 60 seconds per IP
- **Search history** — recent queries stored in localStorage
- **JSON export** — download or copy the full report as JSON

## Tech Stack

| Layer    | Technology                     |
|----------|--------------------------------|
| Backend  | FastAPI, Python 3.11+          |
| Scraping | httpx, BeautifulSoup4          |
| Search   | DuckDuckGo (duckduckgo-search) |
| LLM      | OpenAI GPT-4o (optional)       |
| Frontend | Vanilla HTML/CSS/JS (SSE)      |
| Server   | Uvicorn                        |

## Setup

```bash
# 1. Clone
git clone https://github.com/gitgurudev/Osint.ai.git
cd Osint.ai

# 2. Create virtualenv and install dependencies
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt

# 3. Configure environment
cp .env.example .env
# Edit .env — set OPENAI_API_KEY if you want GPT-4o enhancement
```

## Configuration (`.env`)

| Variable         | Default          | Description                              |
|------------------|------------------|------------------------------------------|
| `OPENAI_API_KEY` | *(empty)*        | GPT-4o key — leave blank for rule-based  |
| `OPENAI_MODEL`   | `gpt-4o`         | Model to use for enhancement             |
| `MAX_URLS`       | `10`             | Number of search result URLs to scrape   |

## Run

```bash
uvicorn app.main:app --reload --port 8000
```

Open [http://localhost:8000](http://localhost:8000) in your browser.

API docs available at [http://localhost:8000/docs](http://localhost:8000/docs).

## API

| Endpoint             | Method | Description                          |
|----------------------|--------|--------------------------------------|
| `/search/stream`     | GET    | SSE stream — real-time pipeline      |
| `/search`            | GET    | JSON response — for curl / API use   |
| `/api/health`        | GET    | Health check, LLM status             |

**Example:**
```bash
curl "http://localhost:8000/search?query=Elon+Musk"
```

## Project Structure

```
osint-ai/
├── app/
│   ├── main.py              # FastAPI app, SSE pipeline, rate limiter
│   ├── core/
│   │   └── config.py        # Settings (env vars)
│   ├── models/
│   │   └── schemas.py       # Pydantic models
│   └── services/
│       ├── search.py        # DuckDuckGo search
│       ├── scraper.py       # Page scraper
│       ├── analyzer.py      # Rule-based entity analysis
│       └── llm.py           # GPT-4o enhancement
├── static/
│   └── index.html           # Single-page frontend
└── requirements.txt
```

## License

MIT
