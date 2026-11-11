import sys
import json
import numpy as np
import pandas as pd
from pathlib import Path
from datetime import datetime, timedelta, timezone
from scipy import signal as sig

import skdh
import tsfel


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


class WindowedFeatureExtractor:
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

    def extract_and_save_metrics(self, signal_window, fs, exercise_name, output_path, f_name):
        magnitude = np.linalg.norm(signal_window, axis=1)
        dynamic_mag = magnitude - np.mean(magnitude)
        df_window = pd.DataFrame({'Magnitude': dynamic_mag})
        
        results = {
            "Metadata": {
                "Sensor": f_name,
                "Exercise": exercise_name,
                "Duration_s": len(signal_window) / fs,
                "Sampling_Rate_Hz": fs
            },
            "Clinical_Metrics": {
                "Mechanical_Load": float(np.sum(np.abs(dynamic_mag)))
            },
            "TSFEL_Features": {}
        }

        f, psd = sig.welch(dynamic_mag, fs=fs, nperseg=min(len(dynamic_mag), 1024))
        if len(psd) > 10:
            amp_norm = np.sqrt(psd) / np.max(np.sqrt(psd))
            results["Clinical_Metrics"]["SPARC_Smoothness"] = float(-np.sum(np.sqrt(np.diff(f)**2 + np.diff(amp_norm)**2)))

        try:
            feats = tsfel.time_series_features_extractor(self.tsfel_config, df_window, fs=fs, verbose=0)
            results["TSFEL_Features"] = feats.to_dict(orient='records')[0]
        except Exception as e:
            results["TSFEL_Features"] = f"Error: {str(e)}"

        with open(output_path / f"{exercise_name}_features.json", 'w', encoding='utf-8') as out:
            json.dump(results, out, indent=4)

    def process_all_files(self):
        base_data_path = Path("./data/sensor_data")
        output_base_path = Path("./Results")
        
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

                    # Print para debug: mostrar a hora de início e fim que o Python "pensa" que o ficheiro tem
                    file_start_str = datetime.fromtimestamp(times[0], tz=timezone.utc).strftime('%Hh%Mm%Ss')
                    file_end_str = datetime.fromtimestamp(times[-1], tz=timezone.utc).strftime('%Hh%Mm%Ss')
                    print(f"  [Sensor Info] Gravação vai das {file_start_str} até às {file_end_str}")
                    
                    sensor_results_path = output_base_path / patient_name / f_path.stem
                    sensor_results_path.mkdir(parents=True, exist_ok=True)

                    for ex_name, times_cfg in exercises.items():
                        if not isinstance(times_cfg, dict): 
                            continue
                        
                        h_start = times_cfg.get("start_time")
                        h_end = times_cfg.get("end_time")
                        
                        idx_start, idx_end = None, None

                        if h_start and h_end:
                            ts_start = self.string_to_timestamp(h_start, times)
                            ts_end = self.string_to_timestamp(h_end, times)
                            
                            if ts_start and ts_end:
                                idx_start = np.searchsorted(times, ts_start)
                                idx_end = np.searchsorted(times, ts_end)

                        if idx_start is not None and 0 <= idx_start < len(accel):
                            print(f"  Extracting {ex_name}...")
                            
                            if idx_end is None or idx_end > len(accel):
                                idx_end = len(accel)
                                
                            segment = accel[idx_start:idx_end]
                            
                            if len(segment) < fs:
                                print(f"    -> [AVISO] Sinal muito curto ou vazio para {ex_name}. Verifica as horas no JSON! A saltar...")
                                continue
                                
                            self.extract_and_save_metrics(segment, fs, ex_name, sensor_results_path, sensor_filename)
                        else:
                            print(f"    -> [AVISO] A hora pedida para '{ex_name}' ({h_start}) não foi encontrada no sensor!")

                except Exception as e:
                    print(f"Error processing {sensor_filename}: {e}")

if __name__ == "__main__":
    extractor = WindowedFeatureExtractor()
    extractor.process_all_files()
    print("\nAll feature extraction tasks completed.")