PYTHON ?= python3
VERILATOR ?= verilator
JOBS ?= 2
MODEL ?= yolox-tiny
RTL = rtl/systolic_pe.sv rtl/systolic_tile.sv

.PHONY: test lint audit audit-both clean
test:
	$(PYTHON) tools/run_rtl_tests.py --verilator $(VERILATOR) --jobs $(JOBS)

lint:
	$(VERILATOR) --lint-only -Wall --top-module systolic_tile $(RTL)

audit:
	$(PYTHON) tools/audit_yolox.py --source build/upstream/YOLOX --model $(MODEL) --output build/$(MODEL)-audit.json

audit-both:
	$(MAKE) audit MODEL=yolox-nano
	$(MAKE) audit MODEL=yolox-tiny
	$(PYTHON) tools/compare_models.py --nano build/yolox-nano-audit.json --tiny build/yolox-tiny-audit.json --output build/model-comparison.json

clean:
	rm -rf build/sim
