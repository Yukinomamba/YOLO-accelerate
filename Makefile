PYTHON ?= python3
VERILATOR ?= verilator
MODEL ?= yolox-tiny
ADAM_BUILD ?= build/adam128
ADAM_RTL = rtl/adam/adam_mul_pair.sv rtl/adam/adam_sdp_ram.sv rtl/adam/adam_mac128.sv rtl/adam/adam_conv128.sv

.PHONY: test lint adam-test adam-lint tile-test audit audit-both clean
test: adam-test

lint: adam-lint

adam-test:
	$(PYTHON) tools/run_adam_tests.py --verilator $(VERILATOR) --build-dir $(ADAM_BUILD)

adam-lint:
	$(PYTHON) tools/run_guarded.py --log $(ADAM_BUILD)/lint.log --metrics $(ADAM_BUILD)/lint.metrics.json -- $(VERILATOR) --lint-only -Wall --top-module adam_conv128 $(ADAM_RTL)

tile-test:
	$(PYTHON) tools/run_guarded.py --log build/sim/guard.log --metrics build/sim/guard.metrics.json -- $(PYTHON) tools/run_rtl_tests.py --verilator $(VERILATOR) --jobs 1

audit:
	$(PYTHON) tools/audit_yolox.py --source build/upstream/YOLOX --model $(MODEL) --output build/$(MODEL)-audit.json

audit-both:
	$(MAKE) audit MODEL=yolox-nano
	$(MAKE) audit MODEL=yolox-tiny
	$(PYTHON) tools/compare_models.py --nano build/yolox-nano-audit.json --tiny build/yolox-tiny-audit.json --output build/model-comparison.json

clean:
	rm -rf build/sim build/adam128
