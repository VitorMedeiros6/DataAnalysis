# Swimming IMU pipeline (PD vs Control): runs every step in the order used for the thesis.
#
#   make              everything: extract -> tables -> results
#   make extract      step 1: read the .cwa recordings and extract features (slow)
#   make tables       step 2: compile the extracted features into CSV tables
#   make results      step 3: statistics, clustering, classifiers and notebooks
#   make validation   Chapter 4 cycle-detection checks (not part of `make`)
#   make clean        delete every generated file (data/ is never touched)
#
# Before the first run, write data/sensor_placement.json and data/tempos_protocolo.json by hand
# (README, sections 3 and 4).
#
# Use another interpreter:            make PYTHON=python3
# Keep a copy of everything printed:  make 2>&1 | tee pipeline.log

PYTHON ?= python
export PYTHONIOENCODING := utf-8

EXTRACT_DIRS = 'Results', 'results_medium_window', 'results_small_window'

# Runs a notebook top to bottom and saves the executed copy in notebook_outputs/
RUN_NOTEBOOK = $(PYTHON) -c "import os, sys, nbformat, nbclient; nb = nbformat.read(sys.argv[1], as_version=4); nbclient.NotebookClient(nb, timeout=3600, kernel_name='python3').execute(); os.makedirs('notebook_outputs', exist_ok=True); nbformat.write(nb, os.path.join('notebook_outputs', sys.argv[1])); print('Executed: notebook_outputs/' + sys.argv[1])"

.NOTPARALLEL:
.PHONY: all extract tables results validation clean

all: extract tables results

# The full-exercise and 250 ms extractors overwrite files but never delete old ones: if a
# window count shrinks between runs, the extra files from the earlier run would stay and be
# counted by analysis_results.py. Extraction therefore always starts from empty folders.
extract:
	@echo ===== Step 1/3: feature extraction from data/sensor_data
	$(PYTHON) -c "import shutil; [shutil.rmtree(d, ignore_errors=True) for d in ($(EXTRACT_DIRS))]"
	$(PYTHON) data_analysis.py
	$(PYTHON) data_analysis_medium.py
	$(PYTHON) data_analysis_small_window.py

tables:
	@echo ===== Step 2/3: feature tables
	$(PYTHON) analysis_results.py
	$(PYTHON) build_isolated_summary.py
	$(PYTHON) analysis_asymmetry.py
	$(PYTHON) build_full_exercise_features.py

results:
	@echo ===== Step 3/3: statistics, clustering and classifiers
	$(RUN_NOTEBOOK) formulas_e_contas.ipynb
	$(RUN_NOTEBOOK) analise_pd_vs_controlo.ipynb
	$(PYTHON) small_window_analysis.py
	$(PYTHON) analysis_granularity.py
	$(PYTHON) full_window_analysis.py
	$(PYTHON) radar_values.py
	$(PYTHON) clustering_analysis.py
	$(PYTHON) classifier_analysis.py
	$(PYTHON) classifier_extended_analysis.py

validation:
	$(PYTHON) validation/test_segmentation.py
	$(PYTHON) validation/test_odek_ozcan_approach.py
	$(PYTHON) validation/test_odek_ozcan_5patients_all_ex.py
	$(PYTHON) validation/diagnose_axis_choice.py

clean:
	$(PYTHON) -c "import glob, os, shutil; [shutil.rmtree(d, ignore_errors=True) for d in ($(EXTRACT_DIRS), 'notebook_outputs')]; [os.remove(f) for p in ('*.csv', '*.xlsx', 'validation/*.csv') for f in glob.glob(p)]"
