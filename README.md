# F1 Insights
A Formula 1 analytics platform that brings race data, championship standings, circuit information and driver
performance insight together in one place. All session times are shown in IST.

Independent platform; not affiliated with Formula 1, the FIA or any team. For information and analysis only; not intended for betting.

## What it does
- **Championship tracker**: official Drivers' standings, the leader, points gaps, and an estimated title chance for every contender.
  Refreshes itself after every Grand Prix, with a probability history and "up / down since last race" for each driver.
- **Race predictor**: win / podium / points probabilities, generated automatically once qualifying is complete.
- **Strategy analytics**: pit-stop counts, likely pit windows, Safety Car odds and tyre-wear modelling per circuit, plus a Strategy Lab.
- **Circuit maps**: clean 2D track layouts with turn numbers, sectors, start/finish and race-day weather.
- **Accuracy**: every prediction scored against the "finish = grid" baseline.

## One-time setup
```
python -m venv .venv
.venv\Scripts\activate                 # Windows   (Mac/Linux: source .venv/bin/activate)
pip install -U -r requirements.txt     # needs Streamlit >= 1.50

python src/build_dataset.py            # race results 2018 -> now              (resumable)
python src/backtest.py                 # trains models + accuracy scoreboard
python src/fetch_schedule.py           # race calendar (IST times)
python src/build_tracks.py             # circuit outlines from telemetry       (resumable)
python src/build_strategy_stats.py     # real pit / tyre statistics            (resumable)
python src/championship.py             # official standings + title chances   (optional: the app does this itself)
```
"Resumable" = if you see "FastF1 limit reached", wait ~60 minutes and run the same command again.

Already have circuits saved from an earlier version? Add sector markers to them with
`python src/build_tracks.py --add-sectors` (re-downloads only circuits that lack sector data).

## Run
```
streamlit run app/app.py               # http://localhost:8501
```
While the app is open, a background job checks every 15 minutes:
- **Championship**: when a Grand Prix is over and its official standings are published, it re-fetches standings and results,
  recomputes everyone's title chances and updates the charts. If the data source is unreachable, or the standings are not
  published yet, the page says so and keeps showing the last saved data. It never presents stale data as an update.
- **Prediction**: about 75 minutes after qualifying it pulls the grid, reads the forecast and publishes the prediction.

Keep it updating without the app open: `python src/auto_update.py --loop 15`

## How the championship numbers are produced
- **Data**: Jolpica-F1 API (the maintained Ergast-compatible source): official standings (sprint points included) and race results.
- **Method**: Monte Carlo, 20,000 simulated seasons. Expected finishing position per driver from this season's results (recent races weigh
  more), plus season-long uncertainty about form, a shared team-level swing, per-race noise and a retirement chance from each driver's record.
  Official points scoring, ties broken by wins. Probabilities across drivers total 100%; drivers who cannot mathematically catch the leader show 0%.
- **Trend**: the simulation is replayed from every completed round using only what was known then, which gives the history and the change since the previous race.
- **Driver photos**: Wikipedia / Wikimedia Commons when available, initials otherwise.
- These are model estimates, not official F1 statistics.

## Deploy (free)
1. Push to GitHub (commit `data/`; `f1_cache/` is already git-ignored).
2. Deploy on Streamlit Community Cloud with main file `app/app.py`.
3. `.github/workflows/update.yml` runs on race weekends, refreshes predictions and data, and the app redeploys itself.

## Tests
`python -m pytest tests`
