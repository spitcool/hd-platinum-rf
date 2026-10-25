/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "capture.h"

static void publish_barrier(void)
{
#if defined(__arm__) || defined(__thumb__)
    __asm__ volatile ("dmb" ::: "memory");
#else
    __asm__ volatile ("" ::: "memory");
#endif
}

void capture_log_init(volatile struct capture_control *c)
{
    volatile uint32_t *words = (volatile uint32_t *)c;
    for (size_t i = 0; i < sizeof(*c) / sizeof(*words); ++i) words[i] = 0;
    c->magic = CAPTURE_MAGIC;
    c->abi_version = CAPTURE_ABI_VERSION;
    c->control_size = sizeof(*c);
    c->record_size = sizeof(struct capture_record);
    c->capacity = CAPTURE_RECORD_CAPACITY;
    c->timer_hz = 1000000;
    c->build_profile = 1;
}

bool capture_config_valid(const volatile struct capture_control *c)
{
    return c->magic == CAPTURE_MAGIC && c->abi_version == CAPTURE_ABI_VERSION &&
        c->control_size == sizeof(*c) && c->record_size == sizeof(struct capture_record) &&
        c->capacity == CAPTURE_RECORD_CAPACITY && c->state == CAPTURE_READY &&
        c->command == CAPTURE_START_TOKEN &&
        (c->channel == 33 || c->channel == 52 || c->channel == 71) &&
        c->duration_us > 0 && c->duration_us <= CAPTURE_MAX_DURATION_US &&
        c->expected_variant == c->ficr_variant;
}

bool capture_log_append(volatile struct capture_control *c,
                        volatile struct capture_record *records,
                        const struct capture_record *record)
{
    if (c->state != CAPTURE_RUNNING) return false;
    if (record->end_us > c->duration_us) {
        ++c->late_end_count;
        return false;
    }
    uint32_t index = c->record_count;
    if (index >= CAPTURE_RECORD_CAPACITY) {
        ++c->dropped_count;
        c->stop_reason = CAPTURE_STOP_CAPACITY;
        return false;
    }
    records[index] = *record;
    records[index].ordinal = index;
    for (unsigned i = 0; i < 3; ++i) records[index].reserved[i] = 0;
    if (index && record->ready_us >= c->last_end_us) {
        uint32_t gap = record->ready_us - c->last_end_us;
        c->total_rearm_gap_us += gap;
        if (gap > c->max_rearm_gap_us) c->max_rearm_gap_us = gap;
    }
    if (record->crc_status == 1) ++c->crc_ok_count;
    else ++c->crc_error_count;
    c->last_end_us = record->end_us;
    publish_barrier();
    c->record_count = index + 1;
    if (index + 1 == CAPTURE_RECORD_CAPACITY) c->stop_reason = CAPTURE_STOP_CAPACITY;
    return true;
}
