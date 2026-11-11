"""
Test script for cycle detection in segmentar_movimentos.

Usage:
  1. Put the .cwa files in data/sensor_data/<participant>/ (or in validation/)
  2. Create validation/test_protocol.json with the same format as tempos_protocolo.json
     (only include the patients/sensors/exercises you want to test)
  3. Optionally set expected cycle counts in test_protocol.json (see below)
  4. Run from the project root: python validation/test_segmentation.py

test_protocol.json format:
{
    "Patient Name": {
        "sensor_file.cwa": {
            "Ex_MI_Pernas": {
                "start_time": "17h10m30s",
                "end_time":   "17h10m45s",
                "expected_cycles": 12        <- optional, for ground-truth comparison
            }
        }
    }
}

For each exercise it will:
  - Print detected cycle count and per-cycle duration
"""

import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone
from scipy.signal import find_peaks, butter, filtfilt

import skdh

TEST_DIR     = Path(__file__).resolve().parent
PROJECT_ROOT = TEST_DIR.parent
PROTOCOL_FILE = TEST_DIR / "test_protocol.json"

# ---------------------------------------------------------------------------
# Core functions (copied from data_analysis_medium.py)
# ---------------------------------------------------------------------------

def parse_timestamp_str(t_str, data_referencia=None):
    h = int(t_str.split('h')[0])
    m = int(t_str.split('h')[1].split('m')[0])
    s = int(t_str.split('m')[1].replace('s', ''))

    if data_referencia is None:
        data_referencia = datetime.today().date()

    dt_naive = datetime.combine(data_referencia, datetime.min.time()) + timedelta(hours=h, minutes=m, seconds=s)
    return dt_naive.replace(tzinfo=timezone.utc)


def string_to_timestamp(time_str, times_array):
    try:
        clean_time = time_str.replace('h', ':').replace('m', ':').replace('s', '').strip()
        parts = clean_time.split(':')
        if len(parts) == 2:
            clean_time += ":00"

        time_obj = datetime.strptime(clean_time, "%H:%M:%S").time()
        base_date = datetime.fromtimestamp(times_array[0], tz=timezone.utc).date()

        for i in range(14):
            test_date = base_date + timedelta(days=i)
            test_dt   = datetime.combine(test_date, time_obj)
            test_ts   = test_dt.replace(tzinfo=timezone.utc).timestamp()
            if times_array[0] <= test_ts <= times_array[-1]:
                return test_ts

        return None
    except Exception as e:
        print(f"  [ERROR] Timestamp conversion failed: {e}")
        return None


FILTER_PAD_S = 3.0  # seconds of context added before/after segment for filtering only

def segmentar_movimentos(df, t_inicio_str, t_fim_str, freq_amostragem=None, data_referencia=None, exercise_name=""):
    t_inicio = parse_timestamp_str(t_inicio_str, data_referencia)
    t_fim    = parse_timestamp_str(t_fim_str, data_referencia)

    # --- core segment (used for output) ---
    segmento = df[(df['timestamp'] >= t_inicio) & (df['timestamp'] <= t_fim)].copy()
    segmento = segmento.reset_index(drop=True)

    if len(segmento) < 10:
        raise ValueError(f"Segment too short ({len(segmento)} samples). Check timestamps.")

    if freq_amostragem is None:
        delta_medio = segmento['timestamp'].diff().dropna().median()
        delta_s = delta_medio.total_seconds() if hasattr(delta_medio, 'total_seconds') else delta_medio
        freq_amostragem = round(1 / delta_s)

    segmento['mag'] = np.sqrt(segmento['x']**2 + segmento['y']**2 + segmento['z']**2)

    nyq = freq_amostragem / 2
    if "Pernas" in exercise_name or "MI" in exercise_name:
        low_hz, high_hz = 0.3, 3.0
        min_dist_s      = 0.8
    else:
        low_hz, high_hz = 0.3, 2.0
        min_dist_s      = 0.9

    low  = low_hz  / nyq
    high = min(high_hz / nyq, 0.99)
    b, a = butter(4, [low, high], btype='band')

    # --- padded segment (used for filtering only) ---
    pad = pd.Timedelta(seconds=FILTER_PAD_S)
    seg_pad = df[(df['timestamp'] >= t_inicio - pad) & (df['timestamp'] <= t_fim + pad)].copy()
    seg_pad['mag'] = np.sqrt(seg_pad['x']**2 + seg_pad['y']**2 + seg_pad['z']**2)

    # How many pad samples ended up on each side
    n_pre = int(((segmento['timestamp'].iloc[0] - seg_pad['timestamp'].iloc[0])
                 .total_seconds()) * freq_amostragem)
    n_core = len(segmento)

    # Filter each signal on the padded segment, then crop to the core window.
    # For each axis we also try abs(signal) to catch exercises where alternating
    # kicks/strokes create negative peaks that find_peaks would otherwise miss.
    candidates = {}
    for col in ('mag', 'x', 'y', 'z'):
        filtered_pad = filtfilt(b, a, seg_pad[col].values)
        filtered_core = filtered_pad[n_pre: n_pre + n_core]
        segmento[f'{col}_filt'] = filtered_core

        for variant, signal in ((col, filtered_core), (f'abs_{col}', np.abs(filtered_core))):
            if variant.startswith('abs_') and col == 'mag':
                continue  # mag is already positive, abs is redundant
            prominencia = signal.std() * 1.0  # 1.0σ — captures lower-amplitude boundary peaks
            picos_c, props_c = find_peaks(
                signal,
                distance=int(freq_amostragem * min_dist_s),
                prominence=prominencia,
            )
            candidates[variant] = (picos_c, props_c, signal)

    # Best signal: most peaks, tie-broken by regularity (low CV of inter-peak intervals).
    def score(item):
        picos_c, props_c, signal = item[1]
        n = len(picos_c)
        if n < 2:
            return (n, 0.0)
        intervals = np.diff(picos_c).astype(float)
        cv = intervals.std() / intervals.mean()
        return (n, -cv)

    # EXPERIMENTAL (test/ only): prefer raw (non-abs) candidates. abs_* was
    # originally meant only to rescue genuinely one-sided movements where the
    # raw axis misses real cycles — but letting it compete freely on raw peak
    # count means it wins whenever the movement has meaningful amplitude in
    # BOTH directions, since abs() can then detect both lobes as separate
    # peaks (roughly doubling the count vs the true cycle rate). Only fall
    # back to abs_* if no raw candidate found a minimally plausible pattern.
    MIN_RAW_PEAKS = 3
    raw_candidates = {k: v for k, v in candidates.items() if not k.startswith('abs_')}
    best_raw_col = max(raw_candidates.items(), key=score)[0]
    if len(raw_candidates[best_raw_col][0]) >= MIN_RAW_PEAKS:
        best_col = best_raw_col
    else:
        best_col = max(candidates.items(), key=score)[0]
    picos, props, best_signal = candidates[best_col]

    # Store the winning signal for plotting
    base_col = best_col.replace('abs_', '')
    if best_col.startswith('abs_'):
        segmento['mag_filtrada'] = np.abs(segmento[f'{base_col}_filt'])
    else:
        segmento['mag_filtrada'] = segmento[f'{best_col}_filt']

    resultados = []
    for i in range(len(picos)):
        idx_pico  = picos[i]
        idx_start = 0 if i == 0 else (picos[i - 1] + idx_pico) // 2
        idx_end   = len(segmento) - 1 if i == len(picos) - 1 else (idx_pico + picos[i + 1]) // 2

        resultados.append({
            'movimento': i + 1,
            'inicio':     segmento['timestamp'].iloc[idx_start],
            'fim':        segmento['timestamp'].iloc[idx_end],
            'duracao_ms': (segmento['timestamp'].iloc[idx_end] - segmento['timestamp'].iloc[idx_start]).total_seconds() * 1000,
        })

    axis_counts = {variant: len(v[0]) for variant, v in candidates.items()}

    return segmento, picos, props, resultados, freq_amostragem, (low_hz, high_hz, min_dist_s), best_col, axis_counts


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    if not PROTOCOL_FILE.exists():
        print(f"[ERROR] Protocol file not found: {PROTOCOL_FILE}")
        print("Create validation/test_protocol.json with your exercise intervals.")
        return

    with open(PROTOCOL_FILE, 'r', encoding='utf-8') as f:
        protocol = json.load(f)

    for patient_name, sensors in protocol.items():
        print(f"\n{'='*60}")
        print(f"Patient: {patient_name}")

        for sensor_filename, exercises in sensors.items():
            cwa_path = PROJECT_ROOT / "data" / "sensor_data" / patient_name / sensor_filename
            if not cwa_path.exists():
                cwa_path = TEST_DIR / sensor_filename
            if not cwa_path.exists():
                print(f"  [SKIP] {sensor_filename} not found in data/sensor_data/ or validation/")
                continue

            print(f"\n  Sensor: {sensor_filename}")

            reader = skdh.io.ReadCwa()
            data   = reader.predict(file=str(cwa_path))
            accel  = data['accel']
            times  = data['time']
            fs     = data['fs']

            print(f"  Recording: {datetime.fromtimestamp(times[0], tz=timezone.utc).strftime('%Hh%Mm%Ss')} -> "
                  f"{datetime.fromtimestamp(times[-1], tz=timezone.utc).strftime('%Hh%Mm%Ss')}  |  fs={fs} Hz")

            df = pd.DataFrame({
                'timestamp': pd.to_datetime(times, unit='s', utc=True),
                'x': accel[:, 0],
                'y': accel[:, 1],
                'z': accel[:, 2],
            })

            for ex_name, cfg in exercises.items():
                if not isinstance(cfg, dict):
                    continue

                h_start  = cfg.get("start_time")
                h_end    = cfg.get("end_time")
                expected = cfg.get("expected_cycles")

                if not h_start or not h_end:
                    print(f"    [SKIP] {ex_name}: missing start_time or end_time")
                    continue

                # Verify timestamps fall within recording
                ts_start = string_to_timestamp(h_start, times)
                ts_end   = string_to_timestamp(h_end, times)
                if ts_start is None or ts_end is None:
                    print(f"    [SKIP] {ex_name}: timestamps {h_start}–{h_end} not found in recording")
                    continue

                print(f"\n    Exercise: {ex_name}  ({h_start} -> {h_end})")

                try:
                    segment_date = pd.to_datetime(times[0], unit='s', utc=True).date()

                    segmento, picos, props, resultados, fs_det, filter_params, best_col, axis_counts = segmentar_movimentos(
                        df, h_start, h_end,
                        freq_amostragem=fs,
                        data_referencia=segment_date,
                        exercise_name=ex_name
                    )

                    axis_str = '  '.join(f'{c}={n}' for c, n in axis_counts.items())
                    print(f"    Filter: {filter_params[0]}-{filter_params[1]} Hz  |  min dist: {filter_params[2]} s")
                    print(f"    Per-axis peaks: {axis_str}  =>  selected: {best_col}")
                    print(f"    Detected: {len(resultados)} cycles" +
                          (f"  |  expected: {expected}  |  diff: {len(resultados) - expected:+d}" if expected is not None else ""))

                    n_cycles = len(resultados)
                    for i, mov in enumerate(resultados):
                        is_boundary = (i == 0 or i == n_cycles - 1)
                        tag = " [boundary]" if is_boundary else ""
                        print(f"      Cycle {mov['movimento']:3d}  |  {mov['duracao_ms']/1000:.2f} s{tag}")

                    # Stats and feature data use only the inner (non-boundary) cycles
                    inner = resultados[1:-1] if n_cycles >= 3 else []
                    if inner:
                        durs = [m['duracao_ms'] / 1000 for m in inner]
                        print(f"    Mean (inner {len(inner)}): {np.mean(durs):.2f} s  |  Std: {np.std(durs):.2f} s")
                    elif n_cycles == 2:
                        print(f"    Only 2 cycles — no inner cycles to average")
                    elif n_cycles == 1:
                        print(f"    Only 1 cycle detected")

                except Exception as e:
                    print(f"    [ERROR] {ex_name}: {e}")

    print("\nDone.")


if __name__ == "__main__":
    main()
