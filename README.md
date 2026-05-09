# ScoutIQ — European Football Analytics

An end-to-end football analytics project covering the **Top 5 European leagues** across **4 seasons** (2022-23 to 2025-26). It combines salary, rating, and performance data into a star-schema data model, and delivers insights through a self-contained interactive HTML dashboard.

**→ [Open the Dashboard](https://co7co7.github.io/scoutiq-football-analytics/)** *(live demo via GitHub Pages)*

---

## What it covers

| League | Country | Seasons |
|---|---|---|
| Premier League | England | 2022-23, 2023-24, 2024-25, 2025-26 |
| LaLiga | Spain | 2022-23, 2023-24, 2024-25, 2025-26 |
| Bundesliga | Germany | 2022-23, 2023-24, 2024-25, 2025-26 |
| Serie A | Italy | 2022-23, 2023-24, 2024-25, 2025-26 |
| Ligue 1 | France | 2022-23, 2023-24, 2024-25, 2025-26 |

> **14,631** player-club-season records · **100% cross-source coverage** · salaries in USD (inflation-adjusted to 2026)

---

## Dashboard — 5 views

| Section | What you see |
|---|---|
| **01 Ligas** | League-level KPIs, total wage bill, fixed vs. bonus split, average rating radar, goals by league, salary evolution 2022→2026 |
| **02 Salarios** | Salary vs. rating scatter, player salary ranking table with search, average wage by league |
| **03 Rendimiento** | Performance stats (goals, assists, minutes), player detail card with radar profile |
| **04 Scouting** | Multi-filter player search across all leagues and seasons with side-by-side comparison |
| **05 Rendimiento Negativo** | Identifies players with high salary and low output — the worst-ROI signings per league/season |

All views support **Temporada** and **Liga** filters simultaneously. The dashboard is a single self-contained HTML file with all data embedded — no backend, no dependencies to install.

---

## Data model — Star schema

```
                     dim_temporada
                          |
    dim_liga ─────┐       |       ┌───── dim_club
                  └──▶ fact_salarios ◀──┘
                  └──▶ fact_rating ◀────┘
                  └──▶ fact_rendimiento ◀┘
                          |
                     dim_jugador
```

| Table | Rows | Description |
|---|---|---|
| `dim_jugador` | 10,547 | Unique players (normalized name + ClubID + season as composite key) |
| `dim_club` | 125 | Clubs with alias mappings per source to resolve name mismatches |
| `dim_liga` | 5 | Leagues with country and logo URL |
| `dim_temporada` | 4 | Seasons 2022-23 → 2025-26 |
| `fact_salarios` | 10,785 | Annual & weekly salary in USD (fixed, bonus, total, inflation-adjusted) |
| `fact_rating` | 8,608 | WhoScored match ratings, minutes, appearances (starts + sub-ins) |
| `fact_rendimiento` | 10,209 | FBref stats: goals, assists, xG, xA, progressive passes/carries |

All fact tables share the same foreign keys: `PlayerID`, `ClubID`, `LigaID`, `TemporadaID`.

---

## Data sources

| Source | Data | Format |
|---|---|---|
| [Capology](https://www.capology.com) | Player salaries (net, fixed + bonus, USD) | Scraped CSV |
| [WhoScored](https://www.whoscored.com) | Match ratings, appearances, minutes | Scraped CSV |
| [FBref](https://fbref.com) | Playing time & performance stats | Scraped HTML → CSV / XLSX |

---

## ETL pipeline

Raw data goes through a multi-step normalization process before building the model:

1. Load and consolidate the 4 sources (2 salary files merged)
2. Fix WhoScored scraping errors — club names embedded in player strings (`"Christopher NkunkuRBL"` → player: `Christopher Nkunku`, club: `RB Leipzig`)
3. Build `dim_liga` and `dim_club` with manual alias mapping across 5 leagues × 4 seasons
4. Resolve ambiguous leagues in the 2025-26 salary file (La Liga + Serie A were unlabeled)
5. Build `dim_jugador` using normalized name (no accents, lowercase) + ClubID + season
6. Assign `ClubID` and `PlayerID` to all fact tables via join on normalized keys
7. Parse WhoScored appearances format: `"31(7)"` → `Starts=31, SubsIn=7, TotalApps=38`
8. Export to individual CSVs and a multi-sheet Excel for Power BI

The result: **0 unmatched records** across all three fact tables.

**Reproducible:** run [`etl_pipeline.py`](Archivos_finales_dashboard/etl_pipeline.py) against the source files to regenerate all outputs.

---

## Tech stack

| Layer | Tools |
|---|---|
| Data wrangling | Python · Pandas · unicodedata |
| Exploration | Jupyter Notebooks |
| Visualization | Chart.js 4.4 · Pure HTML/CSS/JS |
| Data model | Star schema (CSV + Excel) |
| BI-ready output | Power BI compatible (see [`Archivos_finales_dashboard/README.md`](Archivos_finales_dashboard/README.md)) |

---

## Repository structure

```
├── index.html                         # Main interactive dashboard (GitHub Pages entry point)
├── Archivos_finales_dashboard/
│   ├── etl_pipeline.py                # Reproducible ETL script
│   ├── dim_jugador.csv                # Player dimension
│   ├── dim_club.csv                   # Club dimension (with alias mappings)
│   ├── dim_liga.csv                   # League dimension
│   ├── dim_temporada.csv              # Season dimension
│   ├── fact_salarios.csv              # Salary fact table
│   ├── fact_rating.csv                # Rating fact table
│   ├── fact_rendimiento.csv           # Performance fact table
│   ├── modelo_powerbi.xlsx            # All tables in a single Excel file
│   └── README.md                      # Data model technical documentation
├── Script/                            # Jupyter notebooks (per-source ETL)
├── Salarios/                          # Raw salary data by league (Capology)
├── Rating/                            # Raw rating data by league (WhoScored)
└── Rendimiento/                       # Raw performance data by league (FBref)
```

---

## Key analytical findings

- **Salary inflation**: average wages across the Top 5 grew ~28% from 2022-23 to 2025-26 in real terms
- **Efficiency gap**: Premier League clubs spend ~2.5× more per player than Bundesliga clubs on average
- **ROI outliers**: several high-earners score below 6.5 in WhoScored rating with <500 minutes — tracked in the *Rendimiento Negativo* view
- **Cross-source coverage**: 6,197 players appear in all three sources simultaneously (salaries ∩ rating ∩ performance)

---

## How to run locally

```bash
# Clone and open the dashboard
git clone https://github.com/Co7Co7/scoutiq-football-analytics.git
open index.html   # macOS
# or just double-click index.html in Windows/Linux
```

To regenerate the data model from raw sources:

```bash
cd Archivos_finales_dashboard
pip install pandas openpyxl
python etl_pipeline.py
```

---

*Data covers professional contracts and public statistics only. Salary figures are net annual values in USD.*
