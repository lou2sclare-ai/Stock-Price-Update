# Stock Price Update — Sector Dashboard

Free-data automation for listed companies in **shipbuilding / defense / power equipment / construction equipment / machinery**.

## What the system does
- **Domestic universe**: reads NAVER Finance industry membership automatically.
- **Global universe**: reads related TradingView industry groups automatically.
- **Universe refresh**: weekly; new names are added, disappeared names are retained as `REMOVED` and disabled for review instead of being silently deleted.
- **Korea prices**: KRX data via PyKRX.
- **Global prices**: Yahoo Finance via yfinance, with change % recomputed from consecutive daily closes.
- **Outputs**: `data/latest.json`, `output/latest.xlsx`, `data/qa_latest.json`.
- **Website**: static Netlify frontend reads GitHub raw JSON/XLSX, so daily data updates do not require a site rebuild.
- **QA**: duplicate keys, unexpectedly small universe, missing prices, extreme moves, TP/status inconsistencies, and currency mismatches.

## Research sectors
- `SHIPBUILDING` — 조선
- `DEFENSE` — 방산
- `POWER_EQUIPMENT` — 전력기기
- `CONSTRUCTION_EQUIPMENT` — 건설장비
- `MACHINERY` — 기계

NAVER/TradingView classifications are kept in `source_sector` / `source_industry`. The dashboard uses `research_sector`, which can be pinned in `config/settings.yml` under `manual_overrides`.

## First run
1. GitHub → Actions → **Daily stock update** → **Run workflow**.
2. First run creates the universe and daily output files.
3. Review `data/universe_master.csv` and `data/universe_changes.json`.
4. Netlify → Add new project → Import an existing project → choose this repo.
5. `netlify.toml` already sets the publish directory to `website` and ignores data-only commits.

No paid API key is required for V1.

## Notes
- `research_status` starts as `UNDEFINED`; later set `COVERAGE` / `NR` and TP/report dates through overrides or the master file.
- Missing global price mappings are surfaced as QA warnings rather than deleting companies from the universe.
- Public redistribution terms of upstream market-data providers should be reviewed before using the site as a commercial public data service.
