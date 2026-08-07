# EDGE-MODEL — Session Progress & Handoff

> **Purpose of this file:** If Termux/this session dies, this is the single
> reference to resume from. Read it first, then the code. Updated: 2026-08-07.

## 1. What we are building (user's spec, from interview)

**Bettor profile (Jeff):**
- Football **over/under goals** first (NBA totals was the pivot point), tennis second — both offered by his local bookie.
- Daily accumulator: legs at ~1.2–1.7 decimal odds, combined to **~5.0 total odds**, **$100 stake**.
- Bankroll **$2,000**, weekly-positive goal, **5 consecutive losses → forced pause**.
- 30 minutes of research time on game-day morning. Manual odds entry expected (bookie gives decimal odds).
- **Free tools/data only.** No paid APIs.

**Goal:** Fair-line model → flag +EV legs → assemble the day's parlay → briefing report → paper-trade tracking with pause rule.

## 2. Current strategy spec (REWORKED 2026-08-07)

The original strategy (any line, odds 1.2–1.7) was **reworked to a narrow
two-market spec** after a data-schema audit of football-data.co.uk:

- **Markets (whitelist only):** Over 1.5 and Under 4.5 goals (`ALLOWED_MARKETS`).
- **Leg odds window:** [1.15, 1.25] (`MIN_LEG_ODDS=1.15`, `MAX_LEG_ODDS=1.25`).
- **Parlay assembly:** greedy by edge, at most one leg per match, target combined
  odds ≥ 5.0, dynamic leg count 8–13 (`MIN_LEGS=8`, `MAX_LEGS=13`).
- **Skip day** when < 8 playable legs or target unreachable within 13 legs.
- **Min edge:** model prob − fair implied prob ≥ 0.03.
- **Backtest price:** football-data.co.uk only publishes 2.5-line odds, so the
  1.5/4.5 markets are **simulated at flat per-side prices** (see §4).

## 3. Key decisions made

1. **Language/stack:** Pure-stdlib Python (no numpy/scipy/requests at runtime) so CI is trivial and local smoke tests work without installs.
2. **Model:** Dixon-Coles (1997) Poisson — attack/defense per team, home-advantage gamma, low-score tau/rho correction, exponential time decay (decay=0.004), fit by gradient ascent on analytic gradients in log space, LL-evaluated best-state snapshot every 25 iters.
3. **Backtest method:** Walk-forward, weekly refit on history strictly before the window, bet when model prob beats de-vigged implied by ≥ 0.03 edge.
4. **Paper trading first:** no real money until calibration confirms edge. Live beta = log picks + results via `PaperBook` CSV.
5. **Delivery loop (Jeff's standard):** write code → push to GitHub → CI (ruff + mypy + pytest on ubuntu runner) green → done. Local venv at `/tmp/opencode/edge-venv` for fast local test iteration only.

## 4. Backtest findings (2026-08-07, real data)

Data: **5256 matches**, big-5 leagues (E0/SP1/I1/D1/F1), seasons 2324/2425/2526.
Walk-forward, weekly refit, one parlay per matchday, $100 stake.

**True base rates (from raw outcomes, no model):**
- P(O1.5) = 77.6% → fair odds 1.289
- P(U4.5) = 84.4% → fair odds 1.185

**Sim A — flat 1.20 for BOTH markets (original backtest, INFLATED):**
- 218 parlays / 3 seasons, 32.6% hit, **+68.0% ROI** (net +$14,834)
- ⚠️ U4.5 is an ~84% favorite with fair odds ~1.185; pricing it at 1.20
  manufactured a phantom ~4.5pt edge. Not a realistic bookie price.

**Sim B — per-side realistic book prices (O1.5@1.22, U4.5@1.12):**
- 163 parlays / 3 seasons, 22.7% hit, **+22.5% ROI** (net +$3,663)
- Leg hit 86.7%: over legs 908 (84.6%), under legs 830 (89.0%)
- Parlay-feasible matchdays (≥8 qualifiers): **208 of 526** with ≥1 qualifier
- Break-even for 5.0 combined = 20% → 22.7% is above it but the sample
  (163 parlays) is small; treat ROI as *promising, not proven*.

**Key feasibility insight:** a single league alone (EPL) almost never has ≥8
qualifying legs on one matchday (only 2 parlays in 3 seasons). **The 5-league
pool is what makes the daily parlay viable** — 208 playable matchdays / 3
seasons ≈ 1 every 3–4 days.

## 5. Repo layout

```
/root/edge-model/
├── pyproject.toml                     # setuptools, dev deps: pytest/ruff/mypy
├── .github/workflows/ci.yml           # install → ruff → mypy → pytest
├── src/edge_model/
│   ├── data/football_data.py          # football-data.co.uk download+parse (verified schema)
│   ├── data/fixtures.py               # TheOddsAPI live fixtures+odds (ODDS_API_KEY env)
│   ├── model/dixon_coles.py           # fit_model, score_matrix, totals_distribution, p_over
│   ├── value/filter.py                # implied, devig, evaluate_leg, assemble_parlay (skip-day)
│   ├── backtest/backtest.py           # run_backtest (walk-forward vs flat per-side price)
│   ├── track/paper.py                 # PaperBook: CSV log, bankroll, streak, 5-loss pause
│   ├── report/briefing.py             # daily markdown briefing
│   └── cli/daily.py                   # daily script: fit → legs → parlay → briefing → log
└── tests/
    ├── test_value.py                  # implied/devig/parlay tests
    ├── test_model.py                  # Dixon-Coles convergence/sanity tests
    └── test_paper.py                  # tracker/pause tests
```

## 6. Current status (updated 2026-08-07 evening, after live-odds fix)

- [x] git identity = Jeff-tek, Python 3.13, venv `/tmp/opencode/edge-venv` works
- [x] football-data.co.uk schema verified by live download (2526/E0.csv)
- [x] Strategy reworked to O1.5/U4.5 whitelist (filter.py, backtest.py, briefing.py, daily.py)
- [x] pytest: **21 tests green**; ruff clean; mypy strict clean (16 files)
- [x] Real-data walk-forward backtest run: Sim A (flat) and Sim B (per-side) above
- [x] backtest.py uses per-side `BOOK_ODDS` (O1.5@1.22, U4.5@1.12) — commit 70995d5
- [x] README.md written
- [x] Push to GitHub, CI green (commit d613342, CI passed in 23s)
- [x] Live dashboard: GitHub Pages at https://jeff-tek.github.io/edge-model/
  (Dashboard workflow: build 8m34s + deploy 8s green; 58 live fixtures from
  TheOddsAPI across E0/SP1/I1/D1/F1; `ODDS_API_KEY` repo secret IS set)
- [ ] Tennis module (after football validated)
- [ ] Weekly calibration loop (after real bets accumulate)

### GitHub state (verified 2026-08-07 22:10 UTC)
- `origin/main` = `main`, working tree clean, last commit d613342
- CI workflow: green (ruff + mypy + pytest, 23s)
- Dashboard workflow: green (build + deploy), Pages URL returns HTTP 200
- `ODDS_API_KEY` secret set → all 5 league sport keys fetched real fixtures
- `SPORT_KEY` repo variable is empty — harmless, `LEAGUE_SPORT_KEYS` hardcoded
  in fixtures.py covers all model leagues now

## 7. Resume commands (run from /root/edge-model)

```bash
# local test iteration (venv — already created and editable-installed):
/tmp/opencode/edge-venv/bin/python -m pytest -q

# lint + typecheck:
/tmp/opencode/edge-venv/bin/ruff check .
/tmp/opencode/edge-venv/bin/mypy src

# backtest (per-league or pooled):
/tmp/opencode/edge-venv/bin/python - <<'PY'
from edge_model.data.football_data import load_big5
from edge_model.backtest.backtest import run_backtest
m = load_big5()
r = run_backtest(m)
print(r.n_parlays, r.parlay_hit_rate, r.roi)
PY

# daily briefing (manual odds mode):
/tmp/opencode/edge-venv/bin/python -m edge_model.cli.daily \
  --seasons 2324 2425 2526 --leagues E0 SP1 I1 D1 F1 \
  --odds odds_today.csv --bankroll 2000
```

## 8. Immediate next actions

1. ~~Make backtest.py match the honest per-side pricing~~ — done (70995d5)
2. ~~Push to GitHub → CI green~~ — done (d613342, CI + Pages both green)
3. ~~Write README.md~~ — done
4. **Paper-trade forward**: run daily briefing once football season resumes,
   log to `data/paper_trades.csv`, review after 20+ parlays.
5. **Tennis module** (next big feature) — new model league for the local bookie's
   second market; add after football paper-trade data starts accumulating.
