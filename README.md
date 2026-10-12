# QueueLess Campus – Admin Office Waiting-Time Analyzer

Reduces unnecessary waiting at the **fee counter, examination cell and administration office**.
It records token timestamps (or voluntary manual observations), calculates waiting times,
finds **peak-hour patterns**, and suggests **staffing, token allocation and appointment scheduling** changes.

```
token issued ──► service starts ──► (service ends)
issued_at         served_at          finished_at        wait = served_at − issued_at
```

## Quick start

```bash
python -m venv .venv && source .venv/bin/activate      # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python run_demo.py            # 1) CLI demo: average waits + peak-hour chart in outputs/
streamlit run dashboard.py    # 2) interactive dashboard  (http://localhost:8501)
uvicorn api:app --reload      # 3) REST API + docs        (http://127.0.0.1:8000/docs)
python -m pytest              # 4) run the tests
```

In the dashboard click **Load sample data** in the sidebar to get started.
The dashboard and the API share one SQLite file (`queueless.db`, change with the `QUEUELESS_DB` env variable).

## Project structure

```
queueless_campus/
├── app/
│   ├── config.py        counters, working hours, defaults (edit staff/service times here)
│   ├── db.py            SQLite storage: issue / serve / finish tokens, bulk import
│   ├── analytics.py     cleaning, summaries, hourly stats, peak detection, Erlang-C staffing
│   ├── recommender.py   peak-window actions, appointment/token plan, demand re-balancing
│   └── seed.py          realistic sample-data simulator
├── api.py               FastAPI backend
├── dashboard.py         Streamlit dashboard (5 tabs)
├── run_demo.py          command-line demo, saves chart
├── tests/test_core.py   unit tests
└── requirements.txt
```

## Using your own data

Import a CSV (dashboard sidebar, `POST /upload`, or `python run_demo.py --csv file.csv`) with:

| column | required | example |
|---|---|---|
| `counter` | yes | `Fee Counter` |
| `issued_at` | yes | `2026-10-09 11:05:00` |
| `served_at` (service start) | yes | `2026-10-09 11:21:00` |
| `finished_at` | no | `2026-10-09 11:25:00` |
| `token_no`, `service_type` | no | `42`, `Fee receipt` |

Without a token machine, use the **Live queue & entry** tab: staff press *Serve* when they call the next person,
or anyone can add a **manual observation** (arrival time + minutes waited). Manual rows are stored with
`source = manual` so they can be told apart from system tokens.

## How the analysis works

1. **Waiting time** = `served_at − issued_at`. Unserved tokens and negative waits are dropped.
2. **Summary**: average, median, 90th percentile and maximum wait per counter. (Averages hide long waits, so the 90th percentile matters.)
3. **Peak hours**: average tokens per hour on a working day. An hour is a *peak* when it exceeds `mean + k × std` of that counter's hours (`k` = sensitivity slider). Consecutive peaks are merged into windows such as 11:00–13:00.
4. **Staffing**: Erlang-C queueing model finds the fewest staff that keep the expected wait under the target.
5. **Recommendations** per peak window: add temporary staff, cap walk-in tokens, release appointment slots, move flexible requests to quiet hours, and open a fast lane when service times vary a lot.
6. **Appointment plan**: hourly capacity (at 85 % utilisation) split into appointment slots and walk-in tokens. Overflow demand is moved to the nearest hours with spare capacity.

## REST API

| method | path | purpose |
|---|---|---|
| POST | `/tokens` | issue a token `{counter, service_type}` |
| POST | `/tokens/{id}/serve` | service started (ends the wait) |
| POST | `/tokens/{id}/finish` | service finished |
| POST | `/observations` | manual observation `{counter, arrived_at, waited_min}` |
| GET | `/tokens`, `/queue` | recent tokens / tokens still waiting |
| GET | `/analytics/summary`, `/analytics/hourly` | waiting-time stats, hourly stats with peak flags |
| GET | `/recommendations` | suggestions (`target_wait`, `appointment_share`, `sensitivity`) |
| POST | `/seed`, `/upload` | load sample data / import CSV |
| DELETE | `/tokens` | clear all data |

## Roadmap ideas

- Student-facing page or QR code to take a token; SMS/WhatsApp "your turn is near" alerts.
- Demand forecasting per hour (Prophet / gradient boosting) with an exam and fee-deadline calendar.
- User login for staff vs admin, PostgreSQL for multi-user deployment, Docker.
- Before/after pilot report to measure improvement at one counter.

## Privacy

Only a token number and timestamps are stored – no student names or IDs. Tell users that wait times are being recorded.
