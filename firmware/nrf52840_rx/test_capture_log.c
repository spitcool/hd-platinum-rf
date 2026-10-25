/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "capture.h"
#include <assert.h>
#include <stdio.h>
#include <string.h>

static struct capture_control control;
static struct capture_record records[CAPTURE_RECORD_CAPACITY];

static void configured(void)
{
    memset(&control, 0xa5, sizeof(control));
    capture_log_init(&control);
    control.state = CAPTURE_READY;
    control.ficr_variant = 0x41414630;
    control.expected_variant = control.ficr_variant;
    control.command = CAPTURE_START_TOKEN;
    control.channel = 52;
    control.duration_us = 3000000;
}

static void test_command_gate(void)
{
    configured();
    assert(capture_config_valid(&control));
    control.command = 0; assert(!capture_config_valid(&control));
    control.command = CAPTURE_START_TOKEN;
    control.channel = 40; assert(!capture_config_valid(&control));
    control.channel = 33; assert(capture_config_valid(&control));
    control.channel = 71; assert(capture_config_valid(&control));
    control.duration_us = 0; assert(!capture_config_valid(&control));
    control.duration_us = 3000001; assert(!capture_config_valid(&control));
    control.duration_us = 3000000;
    control.expected_variant ^= 1; assert(!capture_config_valid(&control));
    control.expected_variant = control.ficr_variant;
    control.capacity = 4097; assert(!capture_config_valid(&control));
    control.capacity = 4096;
    control.state = CAPTURE_DONE; assert(!capture_config_valid(&control));
}

static void test_bad_crc_and_receiver_gaps(void)
{
    configured();
    struct capture_record first = {
        .ordinal = 999, .ready_us = 40, .address_us = 116, .end_us = 144,
        .rx_crc = 0x1234, .payload = {0x12,0x34,0x6a,0x02,0x01},
        .crc_status = 0, .rssi_sample = 67, .flags = 3, .rxmatch = 0,
        .reserved = {0xff,0xff,0xff}
    };
    assert(!capture_log_append(&control, records, &first)); /* READY is inert */
    control.state = CAPTURE_RUNNING;
    assert(capture_log_append(&control, records, &first));
    assert(control.record_count == 1 && control.crc_error_count == 1);
    assert(records[0].ordinal == 0 && records[0].crc_status == 0);
    assert(!memcmp(records[0].payload, first.payload, 5));
    assert(records[0].rx_crc == 0x1234 && records[0].rssi_sample == 67);
    assert(records[0].reserved[0] == 0 && records[0].reserved[2] == 0);
    struct capture_record second = first;
    second.ready_us = 194; second.address_us = 316; second.end_us = 344;
    second.crc_status = 1;
    assert(capture_log_append(&control, records, &second));
    assert(control.crc_ok_count == 1 && control.crc_error_count == 1);
    assert(control.max_rearm_gap_us == 50 && control.total_rearm_gap_us == 50);
    second.ready_us = 394; second.end_us = 3000001;
    assert(!capture_log_append(&control, records, &second));
    assert(control.record_count == 2 && control.late_end_count == 1);
    assert(control.last_end_us == 344);
}

static void test_capacity_stops_without_overwriting(void)
{
    configured(); control.state = CAPTURE_RUNNING;
    struct capture_record sample = {.flags = 1, .payload = {1,2,3,4,5}};
    for (uint32_t i = 0; i < CAPTURE_RECORD_CAPACITY; ++i) {
        sample.ready_us = i * 200;
        sample.address_us = i * 200 + 16;
        sample.end_us = i * 200 + 44;
        assert(capture_log_append(&control, records, &sample));
    }
    assert(control.record_count == 4096 && control.stop_reason == CAPTURE_STOP_CAPACITY);
    struct capture_record retained = records[4095];
    sample.payload[0] = 99;
    assert(!capture_log_append(&control, records, &sample));
    assert(control.record_count == 4096 && control.dropped_count == 1);
    assert(!memcmp(&retained, &records[4095], sizeof(retained)));
    assert(records[0].payload[0] == 1);
}

int main(void)
{
    test_command_gate();
    test_bad_crc_and_receiver_gaps();
    test_capacity_stops_without_overwriting();
    puts("capture log checks passed");
    return 0;
}
