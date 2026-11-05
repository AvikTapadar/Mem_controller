# 1. Force Make to use the Python from your active .venv
export PYTHON := $(shell which python)

# 2. Add the TB folder to PYTHONPATH so cocotb can find your Python scripts
export PYTHONPATH := $(PWD)/TB:$(PYTHONPATH)

# 3. Simulator setup
SIM ?= icarus
TOPLEVEL_LANG ?= verilog

# 4. Point to your RTL files (Package MUST be first)
VERILOG_SOURCES += $(PWD)/RTL/mem_ctrl_pkg.sv
VERILOG_SOURCES += $(PWD)/RTL/axi_lite_slave_.sv
VERILOG_SOURCES += $(PWD)/RTL/dram_fsm.sv
VERILOG_SOURCES += $(PWD)/RTL/fr_fcfs_arbiter.sv
VERILOG_SOURCES += $(PWD)/RTL/prefetch_buffer.sv
VERILOG_SOURCES += $(PWD)/RTL/stride_prefetcher.sv
VERILOG_SOURCES += $(PWD)/RTL/top.sv

# 5. The exact module name of your top-level RTL block
TOPLEVEL = top 

# 6. The name of your Python test file in the TB folder (without .py)
MODULE = test_mem_ctrl

# Include cocotb's standard makefile rules
include $(shell cocotb-config --makefiles)/Makefile.sim