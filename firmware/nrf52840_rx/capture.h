/* SPDX-License-Identifier: GPL-2.0-or-later */
#ifndef PLATINUM_CAPTURE_H
#define PLATINUM_CAPTURE_H

#include <stdbool.h>
#include <stddef.h>
#include <stdint.h>

#define CAPTURE_MAGIC UINT32_C(0x58524e50) /* little-endian bytes PNRX */
#define CAPTURE_ABI_VERSION UINT32_C(1)
#define CAPTURE_START_TOKEN UINT32_C(0x52585331)
#define CAPTURE_RECORD_CAPACITY UINT32_C(4096)
#define CAPTURE_MAX_DURATION_US UINT32_C(3000000)

enum capture_state {
    CAPTURE_BOOT = 0, CAPTURE_READY = 1, CAPTURE_RUNNING = 2,
    CAPTURE_DONE = 3, CAPTURE_ERROR = 4
};
enum capture_error {
    CAPTURE_ERROR_NONE = 0, CAPTURE_ERROR_CHIP = 1,
    CAPTURE_ERROR_WATCHDOG = 2, CAPTURE_ERROR_CLOCK = 3,
    CAPTURE_ERROR_CONFIG = 4, CAPTURE_ERROR_RADIO = 5,
    CAPTURE_ERROR_EXCEPTION = 6
};
enum capture_stop_reason {
    CAPTURE_STOP_NONE = 0, CAPTURE_STOP_DEADLINE = 1,
    CAPTURE_STOP_CAPACITY = 2, CAPTURE_STOP_ERROR = 3
};
enum capture_record_flags {
    CAPTURE_RECORD_ADDRESS = 1u << 0,
    CAPTURE_RECORD_RSSI = 1u << 1
};

/* All integer fields are little endian. Exactly 32 bytes; no packed accesses. */
struct capture_record {
    uint32_t ordinal;       /* 0: zero based */
    uint32_t address_us;    /* 4: TIMER4 capture at RADIO.ADDRESS */
    uint32_t end_us;        /* 8: TIMER4 capture at RADIO.END */
    uint32_t ready_us;      /* 12: READY/START of this receive attempt */
    uint32_t rx_crc;        /* 16: unmodified RADIO.RXCRC register */
    uint8_t payload[5];     /* 20: payload in DMA byte order */
    uint8_t crc_status;     /* 25: hardware CRCSTATUS, 0 or 1 */
    uint8_t rssi_sample;    /* 26: raw, uncompensated RSSISAMPLE magnitude */
    uint8_t flags;          /* 27: ADDRESS and RSSIEND events observed */
    uint8_t rxmatch;        /* 28: logical address match register */
    uint8_t reserved[3];    /* 29: zero */
};

/* Exactly 256 bytes. Host writes only command/channel/duration/expected_variant
 * after READY, writing command LAST. All other fields are firmware owned.
 * This image accepts ONE run: reload to repeat. No automatic radio start.
 */
struct capture_control {
    uint32_t magic;                 /* 0 */
    uint32_t abi_version;           /* 4 */
    uint32_t control_size;          /* 8 */
    uint32_t record_size;           /* 12 */
    uint32_t capacity;              /* 16 */
    uint32_t state;                 /* 20 */
    uint32_t error;                 /* 24 */
    uint32_t command;               /* 28: CAPTURE_START_TOKEN */
    uint32_t channel;               /* 32: exactly 33, 52, or 71 */
    uint32_t duration_us;           /* 36: 1..3,000,000 */
    uint32_t expected_variant;      /* 40: exact observed FICR.INFO.VARIANT */
    uint32_t record_count;          /* 44: published after record copy */
    uint32_t crc_ok_count;          /* 48 */
    uint32_t crc_error_count;       /* 52 */
    uint32_t dropped_count;         /* 56: completed frame not stored */
    uint32_t radio_irq_count;       /* 60 */
    uint32_t rx_attempt_count;      /* 64: RXEN attempts, including first */
    uint32_t stop_reason;           /* 68 */
    uint32_t stop_us;               /* 72: timer when shutdown completed */
    uint32_t last_end_us;           /* 76 */
    uint32_t max_rearm_gap_us;      /* 80: prior END -> next READY */
    uint32_t total_rearm_gap_us;    /* 84: excludes initial ramp-up */
    uint32_t partial_at_stop;       /* 88: ADDRESS without END */
    uint32_t late_end_count;        /* 92: END after requested deadline */
    uint32_t ficr_part;             /* 96 */
    uint32_t ficr_variant;          /* 100 */
    uint32_t ficr_package;          /* 104 */
    uint32_t ficr_ram_kib;          /* 108 */
    uint32_t ficr_flash_kib;        /* 112 */
    uint32_t ficr_id0;              /* 116: factory word 0x10000130 */
    uint32_t ficr_id1;              /* 120: factory word 0x10000134 */
    uint32_t ficr_id2;              /* 124: evidence only, 0x10000138 */
    uint32_t resetreas;            /* 128: inherited POWER.RESETREAS */
    uint32_t hfclkstat;            /* 132 */
    uint32_t radio_state;          /* 136: final STATE */
    uint32_t timer_hz;             /* 140: 1,000,000 */
    uint32_t records_address;      /* 144: RAM address, also ELF symbol */
    uint32_t build_profile;        /* 148: 1 = reviewed AAF0 / raw 8,5 */
    uint32_t reserved[26];         /* 152..255: zero */
};

_Static_assert(sizeof(struct capture_record) == 32, "record ABI");
_Static_assert(sizeof(struct capture_control) == 256, "control ABI");
_Static_assert(offsetof(struct capture_record, payload) == 20, "payload ABI");
_Static_assert(offsetof(struct capture_control, records_address) == 144, "control ABI");

void capture_log_init(volatile struct capture_control *control);
bool capture_config_valid(const volatile struct capture_control *control);
bool capture_log_append(volatile struct capture_control *control,
                        volatile struct capture_record *records,
                        const struct capture_record *record);

extern volatile struct capture_control capture_control;
extern volatile struct capture_record capture_records[CAPTURE_RECORD_CAPACITY];

#endif
