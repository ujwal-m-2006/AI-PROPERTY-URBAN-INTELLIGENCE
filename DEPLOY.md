# Deployment

Two things to know before starting.

**1. The git repository is scoped to this folder.** It was re-initialised here
deliberately — see the warning at the bottom of this file, which matters more
than anything else in it.

**2. A clone does not carry `data/raw/` (212 MB) or `models/` (176 MB).** Both
are reproducible from the flows in this repo, and one model file alone is 68 MB.
What *is* committed is `data/processed/` and `ml/artifacts/`, so a fresh clone
serves the API and shows every metric immediately — only live model *prediction*
needs the rebuild.

```bash
python scripts/bootstrap.py --check     # what is present, what is missing
python scripts/bootstrap.py             # rebuild it (cached, resumable)
```

---

## Run it locally

```bash
python -m venv backend/.venv
backend/.venv/Scripts/pip install -e "backend[dev]"
```

```bash
cd backend && PYTHONPATH=. python -m uvicorn app.main:app --port 8000
```

```bash
cd frontend && python -m http.server 3000
```

Open <http://localhost:3000>. No database, no Docker, no internet needed at
runtime — the app reads versioned GeoJSON/JSON artefacts.

Verify:

```bash
cd backend && PYTHONPATH=. python scripts/e2e_check.py
```

```bash
cd backend && PYTHONPATH=. python scripts/module_check.py
```

---

## Deploying it publicly

The stack is a stateless FastAPI service plus a static frontend, so most
platforms work. What follows is honest about what has and has not been tested.

### What is verified

* The API runs standalone on uvicorn with no database.
* All 219 tests and 97 end-to-end checks pass locally.
* `infra/docker/api.Dockerfile` and `docker-compose.yml` exist in this repo.

### What is NOT verified

**The Docker build has never been run.** Docker is not installed on the machine
this was developed on, so the Dockerfile is written but untested. Build it once
locally before trusting it in a pipeline:

```bash
docker build -f infra/docker/api.Dockerfile -t gba-api .
```

No cloud deployment has been performed. The steps below are the intended path,
not a record of something that worked.

### Suggested path

| Piece | Option | Note |
|---|---|---|
| API | Render / Railway / Fly.io | Needs ~1 GB RAM — the models load into memory |
| Frontend | GitHub Pages / Netlify / Vercel | Static; set the API base URL |
| Models | Rebuild at deploy time, or attach a volume | 176 MB; do not commit them |

The frontend points at the API through the `API` constant near the top of
`frontend/index.html`. Change it from `http://127.0.0.1:8000/api/v1` to the
deployed origin before publishing the static site.

### Before making it public

This is a research prototype about property and planning data. Two things
deserve a decision rather than a default:

* **The disclaimers are load-bearing.** Every response carries them and the UI
  renders them. They are the reason the project is defensible. Do not strip them
  to make the demo look cleaner.
* **Nothing is authenticated.** There are no user accounts, no rate limiting and
  no abuse controls (Module 35 is PARTIAL for exactly this reason). That is fine
  for a review demo on a private URL. It is not fine for an indexed public
  service — add rate limiting at the platform edge first.

---

## ⚠ The git warning

**The home folder above this project is itself a git repository**, with a remote
pointing at an unrelated repo.

Running `git add -A && git push` from that directory would attempt to commit and
push your **entire home folder** — including `.ssh/` (private keys), `.aws/`
(cloud credentials), `.claude.json`, `NTUSER.DAT`, Documents, Downloads and
browser profiles — to that remote.

This project now has its **own** repository, rooted at this folder, so working
here is safe. But the home-directory repository still exists and is still
dangerous. Recommended:

```bash
cd ~ && git remote remove origin
```

Or remove the repository entirely if it was created by accident:

```bash
cd ~ && rm -rf .git
```

Check what it is first — it has a single commit and one tracked file, so it is
unlikely to be holding anything you need.
