"""Central configuration: counters, working hours and analysis defaults."""
import os

# SQLite database file (override with the QUEUELESS_DB environment variable)
DB_PATH = os.environ.get("QUEUELESS_DB", "queueless.db")

# Working hours: counters are open OPEN_HOUR:00 to CLOSE_HOUR:00
OPEN_HOUR = 9
CLOSE_HOUR = 17

# Analysis defaults (all adjustable from the dashboard)
TARGET_WAIT_MIN = 10.0       # acceptable average wait in minutes
PEAK_SENSITIVITY = 0.75      # an hour is a peak if arrivals > mean + k * std
APPOINTMENT_SHARE = 0.6      # share of capacity reserved for booked appointments
TARGET_UTILIZATION = 0.85    # never plan a counter above 85% busy

# Sample counters used by the data generator and as dashboard defaults.
# "profile" = expected tokens per hour from OPEN_HOUR to CLOSE_HOUR - 1.
COUNTERS = {
    "Fee Counter": {
        "staff": 3,
        "service_min": 4.0,
        "service_types": ["Fee payment", "Fee receipt", "Scholarship query"],
        "profile": [20, 45, 60, 35, 15, 25, 50, 30],
    },
    "Examination Cell": {
        "staff": 2,
        "service_min": 4.0,
        "service_types": ["Admit card", "Result query", "Re-evaluation"],
        "profile": [10, 20, 30, 40, 20, 15, 25, 12],
    },
    "Admin Office": {
        "staff": 3,
        "service_min": 6.0,
        "service_types": ["Bonafide certificate", "Transfer certificate", "ID card"],
        "profile": [15, 25, 28, 30, 22, 20, 26, 18],
    },
}

# Busier at the start of the week (0 = Monday)
WEEKDAY_FACTOR = {0: 1.15, 1: 1.0, 2: 0.95, 3: 1.0, 4: 0.9}

# Fallbacks for counters that appear in uploaded data but not in COUNTERS
DEFAULT_STAFF = 2
DEFAULT_SERVICE_MIN = 5.0
