"""
Everything the pipeline needs to know about each participant, read from data/participants.json.

That file is written by hand, like data/tempos_protocolo.json (README, section 3). It has one
entry per participant, keyed by the participant ID (the folder name in data/sensor_data/):

    {
        "Patient 1": {
            "group":     "PD",
            "right_arm": "12345_0000000000.cwa",
            "left_arm":  "23456_0000000000.cwa",
            "right_leg": "34567_0000000000.cwa",
            "left_leg":  "45678_0000000000.cwa",
            "trunk":     "56789_0000000000.cwa"
        },
        "Control 2": {
            "group":   "Control",
            "exclude": "Same .cwa files as Control 1",
            ...
        }
    }

group       "PD" or "Control". Required.
exclude     Optional: the reason for leaving this participant out of every PD-vs-Control
            comparison.
right_arm, left_arm, right_leg, left_leg, trunk
            Optional: the .cwa file worn there (arm = wrist, leg = ankle, trunk = lower back),
            exactly as named in data/sensor_data/<participant>/. A missing limb is skipped by the
            analysis. The trunk sensor is recorded for completeness; no analysis uses it.

No script contains this information: every script that needs it imports it from here.
Inside the scripts the four limb positions are coded ULR, ULL, LLR, LLL (upper/lower limb,
right/left), and a sensor is identified by the part of its file name before the first "_",
which is how it also appears in the output folder names.
"""
import json
from pathlib import Path

PARTICIPANTS_FILE = Path(__file__).resolve().parent / "data" / "participants.json"

GROUPS = ("PD", "Control")

POSITION_CODES = {
    "right_arm": "ULR",
    "left_arm":  "ULL",
    "right_leg": "LLR",
    "left_leg":  "LLL",
}
TRUNK = "trunk"
FIELDS = ["group", "exclude", *POSITION_CODES, TRUNK]


def sensor_id(file_name):
    """'12345_0000000000.cwa' -> '12345'."""
    return Path(file_name).stem.split("_")[0]


def load_participants(path=PARTICIPANTS_FILE):
    """{participant: entry}, checked against the format above."""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Write it by hand before running the pipeline (README, section 3).")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    for participant, entry in raw.items():
        unknown = sorted(set(entry) - set(FIELDS))
        if unknown:
            raise ValueError(f"{path.name}, {participant}: unknown field {unknown}; "
                             f"the allowed fields are {FIELDS}")
        if entry.get("group") not in GROUPS:
            raise ValueError(f"{path.name}, {participant}: \"group\" must be \"PD\" or \"Control\"")
    return raw


PARTICIPANTS = load_participants()

# Participants left out of every PD-vs-Control comparison -> reason
EXCLUDED = {p: e["exclude"] for p, e in PARTICIPANTS.items() if e.get("exclude")}

# The two groups compared throughout, in file order, excluded participants left out
PD_ALL = [p for p, e in PARTICIPANTS.items() if e["group"] == "PD" and p not in EXCLUDED]
CONTROL_ALL = [p for p, e in PARTICIPANTS.items() if e["group"] == "Control" and p not in EXCLUDED]
GROUP_MAP = {p: "PD" for p in PD_ALL}
GROUP_MAP.update({p: "Control" for p in CONTROL_ALL})

# Every participant ID in the file, excluded ones included. The analysis scripts look IDs up
# through this map: in the original pipeline it turned folder names into anonymized IDs, and
# now that the folders already carry the ID it maps each ID to itself.
ANON = {p: p for p in PARTICIPANTS}

# Limb position -> .cwa file name (used where a recording has to be opened)
PLACEMENT_FILES = {p: {POSITION_CODES[k]: v for k, v in e.items() if k in POSITION_CODES}
                   for p, e in PARTICIPANTS.items()
                   if any(k in e for k in POSITION_CODES)}

# Limb position -> sensor ID (used to match rows of the feature tables)
PLACEMENT = {p: {code: sensor_id(name) for code, name in positions.items()}
             for p, positions in PLACEMENT_FILES.items()}

# Trunk (lower back) sensor file, where one was recorded
TRUNK_FILES = {p: e[TRUNK] for p, e in PARTICIPANTS.items() if TRUNK in e}
