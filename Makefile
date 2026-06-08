PYTHON ?= python3
RESULTS_DIR ?= results
DATA_DIR ?= $(RESULTS_DIR)/data
ifeq ($(origin RUN_ID), undefined)
RUN_ID := $(shell python3 -c 'from datetime import datetime, timezone; import uuid; print(datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:8])')
endif

BENCHMARK_MIN_SIZE ?= 10
BENCHMARK_MAX_SIZE ?= 30
BENCHMARK_ITERATIONS ?= 30
BENCHMARK_SEED ?= 2
SMT_WORKERS ?= 8
OVERLAP_DP_WITH_SMT ?= false
DP_MAX_SIZE ?= 0
STOP_DP_AFTER_TIMEOUT ?= true
GLOBAL_TIMEOUT_SECONDS ?= 0
PROBLEM_TIMEOUT_SECONDS ?= 300
SMT_TIMEOUT_MS ?= 0
SMT_STRATEGIES ?= lazy
SMT_OBJECTIVES ?= auto
BOOTSTRAP_SAMPLES ?= 10000
MIN_PAIRS ?= 10
CANDIDATE_SOLVER ?= smt:lazy:auto

BENCHMARK_PREFIX := $(RESULTS_DIR)/benchmark-$(RUN_ID)
BENCHMARK_DATA_PREFIX := $(DATA_DIR)/benchmark-$(RUN_ID)

.PHONY: benchmark

benchmark:
	@mkdir -p "$(RESULTS_DIR)" "$(DATA_DIR)"
	@for artifact in \
		"$(BENCHMARK_DATA_PREFIX).csv" \
		"$(BENCHMARK_DATA_PREFIX)-summary.csv" \
		"$(BENCHMARK_DATA_PREFIX)-comparisons.csv" \
		"$(BENCHMARK_DATA_PREFIX).png" \
		"$(BENCHMARK_PREFIX).md"; do \
		if [ -e "$$artifact" ]; then \
			echo "Refusing to overwrite existing benchmark artifact $$artifact"; \
			exit 1; \
		fi; \
	done
	$(PYTHON) benchmark.py \
		--min-size $(BENCHMARK_MIN_SIZE) \
		--max-size $(BENCHMARK_MAX_SIZE) \
		--iterations $(BENCHMARK_ITERATIONS) \
		--seed $(BENCHMARK_SEED) \
		--dp-max-size $(DP_MAX_SIZE) \
		--$(if $(filter true,$(STOP_DP_AFTER_TIMEOUT)),stop-dp-after-timeout,no-stop-dp-after-timeout) \
		--global-timeout-seconds $(GLOBAL_TIMEOUT_SECONDS) \
		--problem-timeout-seconds $(PROBLEM_TIMEOUT_SECONDS) \
		--smt-strategies $(SMT_STRATEGIES) \
		--smt-objectives $(SMT_OBJECTIVES) \
		--smt-timeout-ms $(SMT_TIMEOUT_MS) \
		--smt-workers $(SMT_WORKERS) \
		--$(if $(filter true,$(OVERLAP_DP_WITH_SMT)),overlap-dp-with-smt,no-overlap-dp-with-smt) \
		--no-plot \
		--csv "$(BENCHMARK_DATA_PREFIX).csv"
	$(PYTHON) analyze_benchmark.py "$(BENCHMARK_DATA_PREFIX).csv" \
		--candidate "$(CANDIDATE_SOLVER)" \
		--summary-csv "$(BENCHMARK_DATA_PREFIX)-summary.csv" \
		--comparison-csv "$(BENCHMARK_DATA_PREFIX)-comparisons.csv" \
		--plot "$(BENCHMARK_DATA_PREFIX).png" \
		--markdown "$(BENCHMARK_PREFIX).md" \
		--run-id "$(RUN_ID)" \
		--cli-invocation '$(PYTHON) benchmark.py --min-size $(BENCHMARK_MIN_SIZE) --max-size $(BENCHMARK_MAX_SIZE) --iterations $(BENCHMARK_ITERATIONS) --seed $(BENCHMARK_SEED) --dp-max-size $(DP_MAX_SIZE) --$(if $(filter true,$(STOP_DP_AFTER_TIMEOUT)),stop-dp-after-timeout,no-stop-dp-after-timeout) --global-timeout-seconds $(GLOBAL_TIMEOUT_SECONDS) --problem-timeout-seconds $(PROBLEM_TIMEOUT_SECONDS) --smt-strategies $(SMT_STRATEGIES) --smt-objectives $(SMT_OBJECTIVES) --smt-timeout-ms $(SMT_TIMEOUT_MS) --smt-workers $(SMT_WORKERS) --$(if $(filter true,$(OVERLAP_DP_WITH_SMT)),overlap-dp-with-smt,no-overlap-dp-with-smt) --no-plot --csv $(BENCHMARK_DATA_PREFIX).csv' \
		--param "target=benchmark" \
		--param "min_size=$(BENCHMARK_MIN_SIZE)" \
		--param "max_size=$(BENCHMARK_MAX_SIZE)" \
		--param "iterations=$(BENCHMARK_ITERATIONS)" \
		--param "seed=$(BENCHMARK_SEED)" \
		--param "smt_workers=$(SMT_WORKERS)" \
		--param "overlap_dp_with_smt=$(OVERLAP_DP_WITH_SMT)" \
		--param "dp_max_size=$(DP_MAX_SIZE)" \
		--param "stop_dp_after_timeout=$(STOP_DP_AFTER_TIMEOUT)" \
		--param "global_timeout_seconds=$(GLOBAL_TIMEOUT_SECONDS)" \
		--param "problem_timeout_seconds=$(PROBLEM_TIMEOUT_SECONDS)" \
		--param "smt_strategies=$(SMT_STRATEGIES)" \
		--param "smt_objectives=$(SMT_OBJECTIVES)" \
		--param "smt_timeout_ms=$(SMT_TIMEOUT_MS)" \
		--bootstrap-samples $(BOOTSTRAP_SAMPLES) \
		--min-pairs $(MIN_PAIRS)
	@rm -f "$(RESULTS_DIR)/benchmark-latest.md"
	@cp "$(BENCHMARK_PREFIX).md" "$(RESULTS_DIR)/benchmark-latest.md"
	@echo "Wrote benchmark report $(BENCHMARK_PREFIX).md"
