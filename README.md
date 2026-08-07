# edge-model

Fair-line football totals model for daily accumulator betting research.

Pure-stdlib Python (no runtime deps). Fits a Dixon-Coles (1997) Poisson model
on football-data.co.uk history, flags +EV legs on **Over 1.5** and **Under 4.5**
totals (leg odds window 1.15–1.25), and assembles a daily parlay targeting
5.0+ combined odds (8–13 legs, one per match).

## Strategy

- **Markets:** Over 1.5 / Under 4.5 goals only.
- **Leg filter:** model prob must beat the de-vigged bookie implied prob by ≥ 0.03.
- **Parlay:** greedy by edge, ≥ 5.0 combined odds; skip the day if < 8 playable legs.
- **Bankroll guard:** 5 consecutive losses → forced pause (paper tracker).

## Usage

```bash
# daily briefing (manual odds entry)
python -m edge_model.cli.daily \
  --seasons 2324 2425 2526 --leagues E0 SP1 I1 D1 F1 \
  --odds odds_today.csv --bankroll 2000

# walk-forward backtest on real data
python - <<'PY'
from edge_model.data.football_data import load_big5
from edge_model.backtest.backtest import run_backtest
r = run_backtest(load_big5())
print(r.n_parlays, r.parlay_hit_rate, r.roi)
PY
```

Manual odds CSV format:
`league,home,away,side,line,odds[,other_odds]`
(e.g. `E0,Arsenal,West Ham,over,1.5,1.22,1.20`)

## Backtest results (big-5 leagues, 2324–2526)

Walk-forward weekly refit; 1.5/4.5 markets simulated at per-side flat book
prices (O1.5 @ 1.22, U4.5 @ 1.12) since football-data.co.uk only publishes
2.5-line odds.

| metric | value |
|---|---|
| matches | 5,256 |
| parlays / 3 seasons | 163 |
| parlay hit rate | 22.7% (break-even 20% @ 5.0) |
| ROI | +22.5% |
| leg hit rate | 86.7% |
| playable matchdays | 208 of 526 |

*Promising but not proven — small sample. Paper-trade before real money.*

## Development

```bash
pip install -e ".[dev]"
ruff check .
mypy src
pytest
```

CI (GitHub Actions) runs install → ruff → mypy → pytest on every push to `main`.
