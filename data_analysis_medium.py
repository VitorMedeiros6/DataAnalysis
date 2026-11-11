import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone
from scipy import signal as sig
from scipy.signal import find_peaks, butter, filtfilt, detrend
from scipy.integrate import cumulative_trapezoid

import skdh
import tsfel

GRAVITY_MS2 = 9.80665  # skdh.io.ReadCwa returns acceleration in g units, not m/s^2

# Sensor placement: data/sensor_placement.json, read by sensor_placement.py.
# Used only to pick the fixed detection axis (see FIXED_AXIS_BY_LIMB below) for
# swim exercises, where every sensor is processed but only limb-matched ones
# are used downstream. Ex_MS_Bracos/Ex_MI_Pernas don't need this — the
# exercise name alone already implies the limb.
from sensor_placement import PLACEMENT

# Ödek & Özcan (2023) — validated against video ground truth for swimming
# arm-stroke/kick detection: a single fixed axis per limb, low-pass filtered,
# beats adaptive multi-axis selection. Empirically re-validated on this
# project's data (28+ sensor/exercise cases): mean |error| vs the protocol's
# prescribed 10 reps dropped from ~6.3 to ~2.6 cycles using this approach.
FIXED_AXIS_BY_LIMB = {"UL": "y", "LL": "x"}
FIXED_AXIS_LOWPASS_HZ = 2.0
FIXED_AXIS_MIN_PEAKS = 3  # below this, fall back to the old multi-candidate method


def _longest_valid_run(times, fs):
    """
    Some raw .cwa files contain a short garbage segment (a handful of seconds,
    typically with a stale/leftover clock value) at the start and/or a
    corrupted, zero-filled tail at the end, on top of an otherwise clean,
    contiguous recording in between. Both corrupt the simple assumption that
    times[0] and times[-1] bound one monotonic recording, which breaks any
    exercise-window lookup that relies on that range.

    Returns (start_idx, end_idx) of the longest run where consecutive samples
    are consistent with the sensor's own sampling rate (within a generous
    10x tolerance, to absorb ordinary jitter without accepting a multi-hour
    jump). If the whole array is already consistent, returns (0, len(times)).
    """
    if len(times) < 2:
        return 0, len(times)
    expected_gap = 1.0 / fs
    good = np.abs(np.diff(times) - expected_gap) < expected_gap * 10

    best_start = best_len = 0
    run_start = 0
    run_len = 1
    for i, ok in enumerate(good):
        if ok:
            run_len += 1
        else:
            if run_len > best_len:
                best_start, best_len = run_start, run_len
            run_start = i + 1
            run_len = 1
    if run_len > best_len:
        best_start, best_len = run_start, run_len

    return best_start, best_start + best_len


def _limb_type_for_sensor(patient_name, sensor_id, exercise_name):
    """Returns 'UL', 'LL', or None if it can't be determined."""
    if exercise_name == "Ex_MS_Bracos":
        return "UL"
    if exercise_name == "Ex_MI_Pernas":
        return "LL"
    placement = PLACEMENT.get(patient_name)
    if placement is None:
        return None
    if sensor_id in (placement.get("ULR"), placement.get("ULL")):
        return "UL"
    if sensor_id in (placement.get("LLR"), placement.get("LLL")):
        return "LL"
    return None


def parse_timestamp_str(t_str, data_referencia=None):
    """
    Converte '16h47m38s' para um timestamp comparável com o do DataFrame.
    Se o DataFrame usar datetime, usa data_referencia (default: hoje).
    Retorna um datetime timezone-aware em UTC.
    """
    h = int(t_str.split('h')[0])
    m = int(t_str.split('h')[1].split('m')[0])
    s = int(t_str.split('m')[1].replace('s', ''))
    
    if data_referencia is None:
        data_referencia = datetime.today().date()
    
    # Criar datetime naive e depois tornar UTC-aware
    dt_naive = datetime.combine(data_referencia, datetime.min.time()) + timedelta(hours=h, minutes=m, seconds=s)
    return dt_naive.replace(tzinfo=timezone.utc)


FILTER_PAD_S = 3.0  # seconds of context added on each side for filtering only


def segmentar_movimentos(df, t_inicio_str, t_fim_str, freq_amostragem=None, data_referencia=None,
                          exercise_name="", limb_type=None):
    """
    Recebe um DataFrame com dados AX3 e os timestamps em formato '16h47m38s',
    e retorna os timestamps de início e fim de cada braçada/pernada.

    Parâmetros:
        df              : DataFrame completo do sensor com colunas ['timestamp', 'x', 'y', 'z']
                          (deve incluir dados fora da janela do exercício para o filtro ter padding)
        t_inicio_str    : string tipo '16h47m38s'
        t_fim_str       : string tipo '16h48m06s'
        freq_amostragem : Hz (se None, calcula automaticamente)
        data_referencia : date object (se None, usa hoje)
        exercise_name   : nome do exercício (usado para ajustar parâmetros de deteção)
        limb_type       : 'UL' ou 'LL' se conhecido — usa deteção de eixo fixo
                          (Ödek & Özcan, 2023); None cai no método antigo multi-eixo.

    Retorna:
        Lista de dicts [{'movimento': n, 'inicio': t, 'fim': t, 'duracao_ms': ms,
                          'is_boundary': bool}, ...]
        Os ciclos de fronteira (primeiro e último) têm is_boundary=True e devem ser
        excluídos da extração de features pois podem estar incompletos.
    """

    t_inicio = parse_timestamp_str(t_inicio_str, data_referencia)
    t_fim    = parse_timestamp_str(t_fim_str, data_referencia)

    # Core segment (used for output)
    segmento = df[(df['timestamp'] >= t_inicio) & (df['timestamp'] <= t_fim)].copy()
    segmento = segmento.reset_index(drop=True)

    if len(segmento) < 10:
        raise ValueError(f"Segmento demasiado curto ({len(segmento)} amostras). Verifica os timestamps.")

    if freq_amostragem is None:
        delta_medio = segmento['timestamp'].diff().dropna().median()
        delta_s = delta_medio.total_seconds() if hasattr(delta_medio, 'total_seconds') else delta_medio
        freq_amostragem = round(1 / delta_s)
        print(f"[INFO] Frequência detetada: {freq_amostragem} Hz")

    segmento['mag'] = np.sqrt(segmento['x']**2 + segmento['y']**2 + segmento['z']**2)

    # Padded segment for filtering — eliminates filter edge distortion at cycle boundaries
    pad = pd.Timedelta(seconds=FILTER_PAD_S)
    seg_pad = df[(df['timestamp'] >= t_inicio - pad) & (df['timestamp'] <= t_fim + pad)].copy()
    seg_pad['mag'] = np.sqrt(seg_pad['x']**2 + seg_pad['y']**2 + seg_pad['z']**2)

    n_pre  = int(((segmento['timestamp'].iloc[0] - seg_pad['timestamp'].iloc[0])
                  .total_seconds()) * freq_amostragem)
    n_core = len(segmento)

    picos = None
    best_variant = None

    # Preferred method (Ödek & Özcan, 2023): single fixed axis per limb
    # (y for arms, x for legs), low-pass filtered at 2 Hz, simple threshold
    # peak detection. Validated on this project's data to roughly halve the
    # mean cycle-count error vs the protocol's prescribed rep count, compared
    # to the old adaptive multi-axis method below (kept as a fallback for
    # when the limb can't be determined, or the fixed axis finds too little).
    if limb_type in FIXED_AXIS_BY_LIMB:
        axis = FIXED_AXIS_BY_LIMB[limb_type]
        b_lp, a_lp = butter(3, FIXED_AXIS_LOWPASS_HZ / (freq_amostragem / 2), btype='low')
        filtered_pad  = filtfilt(b_lp, a_lp, seg_pad[axis].values)
        filtered_core = filtered_pad[n_pre: n_pre + n_core]
        threshold = filtered_core.mean() + filtered_core.std() * 1.0
        picos_fixed, _ = find_peaks(filtered_core, height=threshold)

        if len(picos_fixed) >= FIXED_AXIS_MIN_PEAKS:
            picos = picos_fixed
            best_variant = f"fixed_{axis}"
            print(f"  [Filtro] {exercise_name}: eixo fixo '{axis}' (limb={limb_type}), "
                  f"passa-baixo {FIXED_AXIS_LOWPASS_HZ} Hz")

    # Fallback: old adaptive multi-axis bandpass method
    if picos is None:
        nyq = freq_amostragem / 2
        if "Pernas" in exercise_name or "MI" in exercise_name:
            low_hz, high_hz = 0.3, 3.0
            min_dist_s      = 0.8
        else:
            low_hz, high_hz = 0.3, 2.0
            min_dist_s      = 0.9  # lowered from 1.3 s — swim cycles can be ~1.3 s

        low  = low_hz  / nyq
        high = min(high_hz / nyq, 0.99)
        b, a = butter(4, [low, high], btype='band')

        print(f"  [Filtro] {exercise_name}: banda {low_hz}-{high_hz} Hz | dist. mín. {min_dist_s} s (fallback)")

        # Run detection on mag, x, y, z and their absolute values (abs catches alternating-sign
        # peaks from flutter kicks / alternating strokes where one direction creates negative peaks)
        candidates = {}
        for col in ('mag', 'x', 'y', 'z'):
            filtered_pad  = filtfilt(b, a, seg_pad[col].values)
            filtered_core = filtered_pad[n_pre: n_pre + n_core]
            for variant, sig_core in ((col, filtered_core), (f'abs_{col}', np.abs(filtered_core))):
                if variant == 'abs_mag':
                    continue  # mag is already positive
                prominencia = sig_core.std() * 1.0
                picos_c, props_c = find_peaks(
                    sig_core,
                    distance=int(freq_amostragem * min_dist_s),
                    prominence=prominencia,
                )
                candidates[variant] = (picos_c, props_c, sig_core)

        # Best signal: most peaks, tie-broken by regularity (low CV of inter-peak intervals)
        def score(item):
            picos_c, _, _ = item[1]
            n = len(picos_c)
            if n < 2:
                return (n, 0.0)
            intervals = np.diff(picos_c).astype(float)
            cv = intervals.std() / intervals.mean()
            return (n, -cv)

        best_variant = max(candidates.items(), key=score)[0]
        picos, _, _ = candidates[best_variant]

    n_detected = len(picos)
    print(f"  [Deteção] {exercise_name}: {n_detected} movimentos (sinal: {best_variant})")

    if n_detected == 0:
        print("[AVISO] Nenhum movimento detetado. Tenta ajustar os parâmetros.")
        return []

    # Build result list; mark first and last as boundary cycles
    resultados = []
    for i in range(n_detected):
        idx_pico  = picos[i]
        idx_start = 0 if i == 0 else (picos[i - 1] + idx_pico) // 2
        idx_end   = n_core - 1 if i == n_detected - 1 else (idx_pico + picos[i + 1]) // 2

        is_boundary = (i == 0 or i == n_detected - 1)

        resultados.append({
            'movimento':   i + 1,
            'inicio':      segmento['timestamp'].iloc[idx_start],
            'fim':         segmento['timestamp'].iloc[idx_end],
            'duracao_ms':  (segmento['timestamp'].iloc[idx_end] - segmento['timestamp'].iloc[idx_start]).total_seconds() * 1000,
            'is_boundary': is_boundary,
        })

    print(f"[OK] {n_detected} movimentos detetados ({n_detected - min(2, n_detected)} para análise, {min(2, n_detected)} fronteira).")
    return resultados


class MediumWindowFeatureExtractor:
    """
    Extractor that segments exercises into individual movements (strokes/kicks)
    using peak detection and extracts metrics for each movement.
    """
    
    def __init__(self, ts_file="data/tempos_protocolo.json"):
        self.tsfel_config = tsfel.get_features_by_domain()
        
        try:
            with open(ts_file, 'r', encoding='utf-8') as f:
                self.protocol_data = json.load(f)
            print(f"JSON loaded. Definitions found for {len(self.protocol_data)} patients.")
        except Exception as e:
            print(f"Error reading '{ts_file}': {e}")
            self.protocol_data = {}

    def string_to_timestamp(self, time_str, times_array):
        try:
            clean_time = time_str.replace('h', ':').replace('m', ':').replace('s', '').strip()
            parts = clean_time.split(':')
            if len(parts) == 2: 
                clean_time += ":00"
            
            time_obj = datetime.strptime(clean_time, "%H:%M:%S").time()
            
            # Usar UTC obriga o Python a ignorar o Fuso Horário / Horário de Verão do teu Windows
            # Isto garante que a hora bate certo a 100% com o que vês no OM GUI!
            base_date = datetime.fromtimestamp(times_array[0], tz=timezone.utc).date()
            
            for i in range(14):
                test_date = base_date + timedelta(days=i)
                test_dt = datetime.combine(test_date, time_obj)
                
                # Gerar timestamp em UTC puro
                test_ts = test_dt.replace(tzinfo=timezone.utc).timestamp()
                
                if times_array[0] <= test_ts <= times_array[-1]:
                    return test_ts
                    
            return None
        except Exception as e:
            print(f"Erro ao converter data: {e}")
            return None

    def extract_and_save_metrics_medium_window(self, accel, times, fs, exercise_name, movements, output_path, f_name):
        """
        Extract metrics from each detected movement.
        Each movement is saved as a separate JSON file.
        
        Parâmetros:
            accel       : numpy array com aceleração [N_samples, 3]
            times       : numpy array com timestamps (epoch seconds)
            fs          : frequência de amostragem (Hz)
            exercise_name : nome do exercício
            movements   : lista de dicts com 'inicio', 'fim', 'movimento' (da função segmentar_movimentos)
            output_path : Path onde guardar os resultados
            f_name      : nome do ficheiro do sensor
        """
        
        n_total    = len(movements)
        n_boundary = sum(1 for m in movements if m.get('is_boundary', False))
        print(f"    -> Processing {n_total} detected movements for {exercise_name} ({n_boundary} boundary, {n_total - n_boundary} for analysis)")

        for mov_data in movements:
            mov_number = mov_data['movimento']
            ts_inicio  = mov_data['inicio'].timestamp()
            ts_fim     = mov_data['fim'].timestamp()
            duracao_ms = mov_data['duracao_ms']
            is_boundary = mov_data.get('is_boundary', False)

            if is_boundary:
                print(f"      [SKIP] Movement {mov_number}: boundary cycle excluded from feature extraction")
                continue
            
            # Encontrar os índices correspondentes aos timestamps
            idx_start = np.searchsorted(times, ts_inicio)
            idx_end = np.searchsorted(times, ts_fim)
            
            if idx_start >= len(accel) or idx_end <= idx_start:
                print(f"    -> [AVISO] Movimento {mov_number}: índices inválidos. Pulando...")
                continue
            
            idx_end = min(idx_end, len(accel))
            movement_segment = accel[idx_start:idx_end]
            
            if len(movement_segment) < 2:
                print(f"    -> [AVISO] Movimento {mov_number}: segmento muito curto. Pulando...")
                continue
            
            # Calcular magnitude e dinâmica
            magnitude = np.linalg.norm(movement_segment, axis=1)
            dynamic_mag = magnitude - np.mean(magnitude)
            df_movement = pd.DataFrame({'Magnitude': dynamic_mag})

            actual_duration = len(movement_segment) / fs

            # Velocity estimate: single integration of the dynamic acceleration,
            # then linear-detrend to remove integration drift (assumes the cycle
            # starts/ends at a similar speed, reasonable for a periodic stroke/kick).
            # Not a true displacement-based velocity (no positional reference) —
            # a relative estimate useful for cross-cycle/limb/patient comparison.
            if len(dynamic_mag) >= 2:
                dynamic_mag_ms2 = dynamic_mag * GRAVITY_MS2
                velocity_raw = cumulative_trapezoid(dynamic_mag_ms2, dx=1.0 / fs, initial=0.0)
                velocity = detrend(velocity_raw)
                avg_velocity = float(np.mean(np.abs(velocity)))
                peak_velocity = float(np.max(np.abs(velocity)))
            else:
                avg_velocity = None
                peak_velocity = None

            results = {
                "Metadata": {
                    "Sensor": f_name,
                    "Exercise": exercise_name,
                    "Movement_Number": mov_number,
                    "Movement_Duration_s": actual_duration,
                    "Movement_Duration_ms": duracao_ms,
                    "Sampling_Rate_Hz": fs,
                    "Samples_Count": len(movement_segment)
                },
                "Clinical_Metrics": {
                    "Mechanical_Load": float(np.sum(np.abs(dynamic_mag))),
                    "Peak_Acceleration": float(np.max(np.abs(dynamic_mag))),
                    "RMS_Acceleration": float(np.sqrt(np.mean(dynamic_mag**2))),
                    "Avg_Velocity": avg_velocity,
                    "Peak_Velocity": peak_velocity
                },
                "TSFEL_Features": {}
            }
            
            # Calcular SPARC smoothness
            try:
                f, psd = sig.welch(dynamic_mag, fs=fs, nperseg=min(len(dynamic_mag), 1024))
                if len(psd) > 10:
                    amp_norm = np.sqrt(psd) / (np.max(np.sqrt(psd)) + 1e-8)
                    results["Clinical_Metrics"]["SPARC_Smoothness"] = float(-np.sum(np.sqrt(np.diff(f)**2 + np.diff(amp_norm)**2)))
            except Exception as e:
                results["Clinical_Metrics"]["SPARC_Smoothness"] = None
                print(f"    -> [AVISO] Erro ao calcular SPARC para movimento {mov_number}: {e}")
            
            # Extrair features TSFEL
            try:
                feats = tsfel.time_series_features_extractor(self.tsfel_config, df_movement, fs=fs, verbose=0)
                results["TSFEL_Features"] = feats.to_dict(orient='records')[0]
            except Exception as e:
                results["TSFEL_Features"] = f"Error: {str(e)}"
                print(f"    -> [AVISO] Erro ao extrair TSFEL features para movimento {mov_number}: {e}")
            
            # Guardar este movimento como um ficheiro JSON separado
            movement_filename = f"{exercise_name}_movement_{mov_number:04d}.json"
            with open(output_path / movement_filename, 'w', encoding='utf-8') as out:
                json.dump(results, out, indent=4)
            
            print(f"      [OK] Movement {mov_number} ({duracao_ms:.1f} ms) - saved as {movement_filename}")

    def process_all_files(self):
        base_data_path = Path("./data/sensor_data")
        output_base_path = Path("./results_medium_window")
        
        for patient_name, sensors in self.protocol_data.items():
            print(f"\n--- Processing Patient: {patient_name} ---")
            
            patient_folder = base_data_path / patient_name
            if not patient_folder.exists():
                print(f"Warning: Folder not found for {patient_name} at {patient_folder}")
                continue

            for sensor_filename, exercises in sensors.items():
                f_path = patient_folder / sensor_filename
                
                if not f_path.exists():
                    print(f"Skipping: File {sensor_filename} not found in {patient_folder}")
                    continue

                print(f"Processing Sensor: {sensor_filename}")
                
                try:
                    reader = skdh.io.ReadCwa()
                    data = reader.predict(file=str(f_path))
                    
                    accel = data['accel']
                    times = data['time']
                    fs = data['fs']

                    # Discard any leading/trailing garbage segment (stale clock value at
                    # the start, corrupted zero-filled tail, or both) so that times[0]
                    # and times[-1] genuinely bound one contiguous, monotonic recording.
                    # See _longest_valid_run for why this is necessary.
                    valid_start, valid_end = _longest_valid_run(times, fs)
                    if valid_start != 0 or valid_end != len(times):
                        n_lead, n_trail = valid_start, len(times) - valid_end
                        print(f"  [AVISO] Raw file has an inconsistent timestamp gap; discarding "
                              f"{n_lead} leading and {n_trail} trailing sample(s) outside the "
                              f"longest contiguous run.")
                        times = times[valid_start:valid_end]
                        accel = accel[valid_start:valid_end]

                    # Debug: mostrar a hora de início e fim
                    file_start_str = datetime.fromtimestamp(times[0], tz=timezone.utc).strftime('%Hh%Mm%Ss')
                    file_end_str = datetime.fromtimestamp(times[-1], tz=timezone.utc).strftime('%Hh%Mm%Ss')
                    print(f"  [Sensor Info] Recording from {file_start_str} to {file_end_str}")
                    
                    sensor_results_path = output_base_path / patient_name / f_path.stem
                    sensor_results_path.mkdir(parents=True, exist_ok=True)

                    # Build full-sensor DataFrame once — segmentar_movimentos needs data
                    # outside each exercise window to avoid filter edge distortion
                    df_full = pd.DataFrame({
                        'timestamp': pd.to_datetime(times, unit='s', utc=True),
                        'x': accel[:, 0],
                        'y': accel[:, 1],
                        'z': accel[:, 2],
                    })

                    for ex_name, times_cfg in exercises.items():
                        if not isinstance(times_cfg, dict):
                            continue

                        h_start = times_cfg.get("start_time")
                        h_end = times_cfg.get("end_time")

                        if not h_start or not h_end:
                            print(f"  Skipping {ex_name}: missing start_time or end_time")
                            continue

                        ts_start = self.string_to_timestamp(h_start, times)
                        ts_end = self.string_to_timestamp(h_end, times)

                        if ts_start is None or ts_end is None:
                            print(f"  [AVISO] Could not parse timestamps for '{ex_name}' ({h_start} - {h_end}). Skipping...")
                            continue

                        idx_start = np.searchsorted(times, ts_start)
                        idx_end = np.searchsorted(times, ts_end)

                        if not (0 <= idx_start < len(accel) and idx_end <= len(accel)):
                            print(f"  [AVISO] Invalid indices for '{ex_name}'. Skipping...")
                            continue

                        segment       = accel[idx_start:idx_end]
                        segment_times = times[idx_start:idx_end]

                        if len(segment) < fs:
                            print(f"    -> [AVISO] Signal too short for {ex_name}. Skipping...")
                            continue

                        print(f"  Segmenting movements for {ex_name}...")

                        # Clear any stale movement JSONs from a previous run — cycle
                        # counts/boundary flags can shift between runs, and leftover
                        # files would otherwise be picked up by analysis_results.py
                        # as if they were still current.
                        for stale in sensor_results_path.glob(f"{ex_name}_movement_*.json"):
                            stale.unlink()

                        segment_date = pd.to_datetime(segment_times[0], unit='s', utc=True).date()
                        sensor_id = sensor_filename.split('_')[0]
                        limb_type = _limb_type_for_sensor(patient_name, sensor_id, ex_name)

                        try:
                            movements = segmentar_movimentos(
                                df_full,
                                h_start,
                                h_end,
                                freq_amostragem=fs,
                                data_referencia=segment_date,
                                exercise_name=ex_name,
                                limb_type=limb_type
                            )

                            if movements:
                                self.extract_and_save_metrics_medium_window(
                                    segment, segment_times, fs, ex_name, movements,
                                    sensor_results_path, sensor_filename
                                )
                            else:
                                print(f"    -> No movements detected for {ex_name}")

                        except Exception as e:
                            print(f"    -> [ERRO] Error segmenting movements for {ex_name}: {e}")
                            continue

                except Exception as e:
                    print(f"Error processing {sensor_filename}: {e}")


if __name__ == "__main__":
    extractor = MediumWindowFeatureExtractor()
    extractor.process_all_files()
    print("\nAll feature extraction tasks completed.")
