"""
Where each participant wore each sensor, read from data/sensor_placement.json.

That file is written by hand, like data/tempos_protocolo.json (README, section 3):

    {
        "Patient 1": {
            "right_arm": "12345_0000000000.cwa",
            "left_arm":  "23456_0000000000.cwa",
            "right_leg": "34567_0000000000.cwa",
            "left_leg":  "45678_0000000000.cwa"
        }
    }

Arm sensors are worn on the wrist, leg sensors on the ankle. Each value is the .cwa file name
exactly as it appears in data/sensor_data/<participant>/. A participant or a position may be
left out; the analysis then skips that limb.

Inside the scripts the four positions are coded ULR, ULL, LLR, LLL (upper/lower limb,
right/left), and a sensor is identified by the part of its file name before the first "_",
which is how it also appears in the output folder names.
"""
import json
from pathlib import Path

PLACEMENT_FILE = Path(__file__).resolve().parent / "data" / "sensor_placement.json"

POSITION_CODES = {
    "right_arm": "ULR",
    "left_arm":  "ULL",
    "right_leg": "LLR",
    "left_leg":  "LLL",
}


def sensor_id(file_name):
    """'12345_0000000000.cwa' -> '12345'."""
    return Path(file_name).stem.split("_")[0]


def load_placement_files(path=PLACEMENT_FILE):
    """{participant: {"ULR": file name, "ULL": file name, "LLR": file name, "LLL": file name}}"""
    path = Path(path)
    if not path.exists():
        raise FileNotFoundError(
            f"{path} not found. Write it by hand before running the pipeline (README, section 3).")
    with open(path, encoding="utf-8") as f:
        raw = json.load(f)
    placement = {}
    for participant, positions in raw.items():
        unknown = sorted(set(positions) - set(POSITION_CODES))
        if unknown:
            raise ValueError(f"{path.name}, {participant}: unknown position {unknown}; "
                             f"the allowed positions are {list(POSITION_CODES)}")
        placement[participant] = {POSITION_CODES[pos]: name for pos, name in positions.items()}
    return placement


# Position -> .cwa file name (used where a recording has to be opened)
PLACEMENT_FILES = load_placement_files()

# Position -> sensor ID (used to match rows of the feature tables)
PLACEMENT = {participant: {code: sensor_id(name) for code, name in positions.items()}
             for participant, positions in PLACEMENT_FILES.items()}
