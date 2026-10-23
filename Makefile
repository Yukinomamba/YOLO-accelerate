PYTHON ?= python3
VERILATOR ?= verilator
JOBS ?= 2
RTL = rtl/systolic_pe.sv rtl/systolic_tile.sv

.PHONY: test lint audit clean
test:
	$(PYTHON) tools/run_rtl_tests.py --verilator $(VERILATOR) --jobs $(JOBS)

lint:
	$(VERILATOR) --lint-only -Wall --top-module systolic_tile $(RTL)

audit:
	$(PYTHON) tools/audit_yolox.py --source build/upstream/YOLOX --output build/yolox-audit.json

clean:
	rm -rf build/sim
