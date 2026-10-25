# SPDX-License-Identifier: GPL-2.0-or-later
# CROSS_COMPILE may be an absolute path ending in arm-none-eabi-.
CROSS_COMPILE ?= arm-none-eabi-
HOST_CC ?= cc
BUILD_DIR ?= build
CC = $(CROSS_COMPILE)gcc
OBJDUMP = $(CROSS_COMPILE)objdump
NM = $(CROSS_COMPILE)nm
SIZE = $(CROSS_COMPILE)size
CFLAGS = -std=c11 -Os -g3 -mcpu=cortex-m4 -mthumb -mfloat-abi=soft \
         -ffreestanding -fno-builtin -fno-common -fno-unwind-tables \
         -fno-asynchronous-unwind-tables -ffunction-sections -fdata-sections \
         -Wall -Wextra -Werror
LDFLAGS = -nostdlib -Wl,--gc-sections,--build-id=none,-Map,$(BUILD_DIR)/receiver.map \
          -Wl,--no-undefined -T ram.ld

.PHONY: all clean check-host inspect
all: $(BUILD_DIR)/receiver.elf

$(BUILD_DIR):
	mkdir -p "$@"

$(BUILD_DIR)/receiver.elf: startup.S main.c capture_log.c memory.c capture.h registers.h ram.ld Makefile | $(BUILD_DIR)
	$(CC) $(CFLAGS) startup.S main.c capture_log.c memory.c $(LDFLAGS) -o "$@"
	$(SIZE) "$@"
	$(NM) -n "$@" > "$(BUILD_DIR)/receiver.symbols"

check-host: | $(BUILD_DIR)
	$(HOST_CC) -std=c11 -Wall -Wextra -Werror capture_log.c test_capture_log.c -o "$(BUILD_DIR)/test_capture_log"
	"$(BUILD_DIR)/test_capture_log"

inspect: $(BUILD_DIR)/receiver.elf
	$(OBJDUMP) -h -d "$<" > "$(BUILD_DIR)/receiver.disassembly"

clean:
	rm -rf "$(BUILD_DIR)"
