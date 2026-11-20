MUSA_PATH ?= /usr/local/musa
MCC ?= $(MUSA_PATH)/bin/mcc

MUSA_TARGET := bound_demo_musa
MUSA_SRC := bound_demo.mu

MCCFLAGS := -mtgpu --offload-arch=mp_31 -O3 -std=c++17 -g \
	-I$(MUSA_PATH)/include

.PHONY: all musa clean run

all: musa

musa: $(MUSA_SRC)
	$(MCC) $(MCCFLAGS) -o $(MUSA_TARGET) $(MUSA_SRC)

run: $(MUSA_TARGET)
	./$(MUSA_TARGET)

clean:
	rm -f $(MUSA_TARGET)
