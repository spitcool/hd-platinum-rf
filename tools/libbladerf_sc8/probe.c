/*
 * SPDX-FileCopyrightText: 2026 Christopher Spitler
 * SPDX-License-Identifier: LGPL-2.1-or-later
 *
 * Inert test driver for separately supplied Nuand TX source. The generated
 * SOURCE_FILE and copied upstream headers retain their original notices.
 * There is no libbladeRF linkage, device access, thread, or USB implementation.
 */
#include <assert.h>
#include <stdbool.h>
#include <stdint.h>
#include <stddef.h>
#include <stdlib.h>
#include <stdio.h>
#include <string.h>
#include <limits.h>
#include <inttypes.h>
#include <libbladeRF.h>
#include "sync.h"

/* Portable host/little-endian conversions for the actual metadata header. */
static uint64_t little_endian(uint64_t value, unsigned width)
{
    const uint16_t one = 1;
    if (*(const uint8_t *)&one) return value;
    uint64_t swapped = 0;
    for (unsigned i = 0; i < width; ++i) {
        swapped = (swapped << 8) | (value & 255);
        value >>= 8;
    }
    return swapped;
}
#define HOST_TO_LE64(x) little_endian((x), 8)
#define HOST_TO_LE32(x) ((uint32_t)little_endian((x), 4))
#define HOST_TO_LE16(x) ((uint16_t)little_endian((x), 2))
#define LE64_TO_HOST(x) HOST_TO_LE64(x)
#define LE32_TO_HOST(x) HOST_TO_LE32(x)
#define LE16_TO_HOST(x) HOST_TO_LE16(x)
#include "metadata.h"

#define log_debug(...) ((void)0)
#define log_verbose(...) ((void)0)
#define log_critical(...) ((void)0)
#define FIELD_INIT(field, value) field = value
#define SYNC_WORKER_START_TIMEOUT_MS 250
#define SYNC_WORKER_START 1

static unsigned int uint_min(unsigned int a, unsigned int b)
{
    return a < b ? a : b;
}

typedef enum { SYNC_WORKER_STATE_IDLE, SYNC_WORKER_STATE_RUNNING } sync_worker_state;
struct fake_stream { struct bladerf_sync *owner; size_t bytes; };
struct sync_worker { struct fake_stream *stream; };

static sync_worker_state sync_worker_get_state(struct sync_worker *worker, int *error)
{
    (void)worker;
    if (error) *error = 0;
    return SYNC_WORKER_STATE_RUNNING;
}
static void sync_worker_submit_request(struct sync_worker *worker, int request)
{
    (void)worker;
    (void)request;
}
static int sync_worker_wait_for_state(struct sync_worker *worker, int state, unsigned timeout)
{
    (void)worker;
    (void)state;
    (void)timeout;
    return 0;
}
static int wait_for_buffer(struct buffer_mgmt *buffers, unsigned timeout,
                           const char *function, unsigned index)
{
    (void)timeout;
    (void)function;
    buffers->status[index] = SYNC_BUFFER_EMPTY;
    return 0;
}
static size_t async_stream_buf_bytes(struct fake_stream *stream)
{
    return stream->bytes;
}

static const uint8_t *expected;
static FILE *sc16_wire;
static bool force_zero_timestamp;
static size_t expected_bytes, seen_bytes, submitted_buffers;
static size_t header_errors, data_errors, padding_errors, guard_errors;
static uint64_t wanted_timestamp, message_number, first_timestamp, last_timestamp;

static void reset_expectation(const uint8_t *data, size_t count, uint64_t timestamp)
{
    expected = data;
    expected_bytes = count;
    seen_bytes = submitted_buffers = 0;
    header_errors = data_errors = padding_errors = guard_errors = 0;
    wanted_timestamp = timestamp;
    message_number = first_timestamp = last_timestamp = 0;
    force_zero_timestamp = false;
}

/* Substitute only the transport: inspect the actual serializer's full buffers. */
static int async_submit_stream_buffer(struct fake_stream *stream, void *buffer,
                                     size_t *length, unsigned timeout, bool nonblock)
{
    (void)timeout;
    (void)nonblock;
    struct bladerf_sync *s = stream->owner;
    if (*length != stream->bytes) abort();
    if (s->stream_config.format == BLADERF_FORMAT_SC16_Q11_META &&
        fwrite(buffer, 1, *length, sc16_wire) != *length) abort();

    uint8_t *p = buffer;
    size_t bps = s->stream_config.bytes_per_sample;
    size_t spm = s->meta.samples_per_msg;
    for (size_t offset = 0; offset < *length; offset += s->meta.msg_size) {
        uint64_t timestamp = metadata_get_timestamp(p + offset);
        if (!message_number) first_timestamp = timestamp;
        last_timestamp = timestamp;
        uint64_t expected_timestamp = force_zero_timestamp ? 0 :
                                      wanted_timestamp + message_number * spm;
        if (timestamp != expected_timestamp || metadata_get_flags(p + offset) != 0 ||
            metadata_get_packet_len(p + offset) != 0) ++header_errors;

        size_t bytes = spm * bps;
        size_t copy = seen_bytes < expected_bytes ? expected_bytes - seen_bytes : 0;
        if (copy > bytes) copy = bytes;
        if (copy && memcmp(p + offset + METADATA_HEADER_SIZE,
                           expected + seen_bytes, copy)) ++data_errors;
        for (size_t j = copy; j < bytes; ++j) {
            if (p[offset + METADATA_HEADER_SIZE + j]) {
                ++padding_errors;
                break;
            }
        }
        seen_bytes += bytes;
        ++message_number;
    }
    for (size_t j = 0; j < 32; ++j) {
        if (p[(ptrdiff_t)j - 32] != 0xa5 || p[*length + j] != 0xa5) ++guard_errors;
    }
    ++submitted_buffers;
    /* The inert worker immediately releases submitted buffers for reuse. */
    for (unsigned i = 0; i < s->buf_mgmt.num_buffers; ++i) {
        if (s->buf_mgmt.buffers[i] == buffer) s->buf_mgmt.status[i] = SYNC_BUFFER_EMPTY;
    }
    return 0;
}

#ifndef SOURCE_FILE
#error SOURCE_FILE must identify one of the generated upstream variants
#endif
#include SOURCE_FILE

static void *checked_calloc(size_t count, size_t size)
{
    void *p = calloc(count, size);
    if (!p) abort();
    return p;
}

/* Explicit fixture, not execution or emulation of sync_init/device setup. */
static void init(struct bladerf_sync *s, int format, size_t message_size)
{
    memset(s, 0, sizeof(*s));
    s->initialized = true;
    s->state = SYNC_STATE_BUFFER_READY;
    s->stream_config.format = format;
    s->stream_config.layout = BLADERF_TX_X1;
    s->stream_config.samples_per_buffer = 65536;
    s->stream_config.bytes_per_sample = format == BLADERF_FORMAT_SC8_Q7_META ? 2 : 4;
    s->stream_config.timeout_ms = 3000;
    s->meta.state = SYNC_META_STATE_HEADER;
    s->meta.msg_size = message_size;
    s->meta.samples_per_msg = samples_per_msg(message_size, s->stream_config.bytes_per_sample);
    s->meta.msg_per_buf = msg_per_buf(message_size, 65536, s->stream_config.bytes_per_sample);
    s->meta.samples_per_ts = 1;
    s->buf_mgmt.num_buffers = 2;
    s->buf_mgmt.submitter = SYNC_TX_SUBMITTER_FN;
    s->buf_mgmt.status = checked_calloc(2, sizeof(*s->buf_mgmt.status));
    s->buf_mgmt.actual_lengths = checked_calloc(2, sizeof(size_t));
    s->buf_mgmt.buffers = checked_calloc(2, sizeof(void *));
    size_t bytes = 65536 * s->stream_config.bytes_per_sample;
    for (unsigned i = 0; i < 2; ++i) {
        uint8_t *p = checked_calloc(bytes + 64, 1);
        memset(p, 0xa5, bytes + 64);
        s->buf_mgmt.buffers[i] = p + 32;
    }
    s->worker = checked_calloc(1, sizeof(*s->worker));
    s->worker->stream = checked_calloc(1, sizeof(*s->worker->stream));
    s->worker->stream->owner = s;
    s->worker->stream->bytes = bytes;
}

static void destroy(struct bladerf_sync *s)
{
    for (unsigned i = 0; i < 2; ++i) free((uint8_t *)s->buf_mgmt.buffers[i] - 32);
    free(s->buf_mgmt.buffers);
    free(s->buf_mgmt.status);
    free(s->buf_mgmt.actual_lengths);
    free(s->worker->stream);
    free(s->worker);
}

static uint8_t *input(size_t count)
{
    uint8_t *p = checked_calloc(count, 1);
    for (size_t i = 0; i < count; ++i) p[i] = (uint8_t)(1 + i % 251);
    if (count >= 12) memset(p + count - 12, 0, 12);
    return p;
}

static bool valid_burst(int status, size_t bytes, struct bladerf_sync *s,
                        struct bladerf_metadata *metadata)
{
    return status == 0 && seen_bytes >= bytes && header_errors == 0 &&
           data_errors == 0 && padding_errors == 0 && guard_errors == 0 &&
           !s->meta.in_burst && metadata->status == 0;
}

static void run_case(int format, size_t message_size, unsigned count, bool split, bool now)
{
    struct bladerf_sync s;
    init(&s, format, message_size);
    size_t bps = s.stream_config.bytes_per_sample;
    size_t bytes = (size_t)count * bps;
    uint8_t *data = input(bytes);
    struct bladerf_metadata metadata = {0};
    metadata.timestamp = 1000000;
    metadata.flags = BLADERF_META_FLAG_TX_BURST_START |
                     (split ? 0 : BLADERF_META_FLAG_TX_BURST_END);
    metadata.status = 1234;
    if (now) metadata.flags |= BLADERF_META_FLAG_TX_NOW;
    reset_expectation(data, bytes, metadata.timestamp);
    force_zero_timestamp = now;
    int status;
    if (split) {
        unsigned first = count / 3;
        status = sync_tx(&s, data, first, &metadata, 3000);
        if (status == 0) {
            metadata.flags = BLADERF_META_FLAG_TX_BURST_END;
            status = sync_tx(&s, data + first * bps, count - first, &metadata, 3000);
        }
    } else {
        status = sync_tx(&s, data, count, &metadata, 3000);
    }
    size_t actual_seen = seen_bytes, actual_buffers = submitted_buffers;
    size_t herr = header_errors, derr = data_errors, perr = padding_errors, gerr = guard_errors;
    uint64_t fts = first_timestamp, lts = last_timestamp;
    bool first_ok = valid_burst(status, bytes, &s, &metadata);

    /* A successful END must allow the next START on this same stream. */
    uint64_t next = 1000000 + (seen_bytes / bps) + 1000000;
    metadata.timestamp = next;
    metadata.flags = BLADERF_META_FLAG_TX_BURST_START | BLADERF_META_FLAG_TX_BURST_END;
    metadata.status = 1234;
    reset_expectation(data, bytes, next);
    int second = sync_tx(&s, data, count, &metadata, 3000);
    bool second_ok = valid_burst(second, bytes, &s, &metadata);
    printf("{\"format\":%d,\"bps\":%zu,\"message_bytes\":%zu,\"sample_count\":%u,"
           "\"split\":%s,\"now\":%s,\"first_rc\":%d,\"first_ok\":%s,"
           "\"second_rc\":%d,\"second_ok\":%s,\"buffers\":%zu,"
           "\"serialized_data_bytes\":%zu,\"header_errors\":%zu,\"data_errors\":%zu,"
           "\"padding_errors\":%zu,\"guard_errors\":%zu,\"first_header_timestamp\":%" PRIu64 ","
           "\"last_header_timestamp\":%" PRIu64 "}\n",
           format, bps, message_size, count, split ? "true" : "false", now ? "true" : "false",
           status, first_ok ? "true" : "false", second, second_ok ? "true" : "false",
           actual_buffers, actual_seen, herr, derr, perr, gerr, fts, lts);
    free(data);
    destroy(&s);
}

static void parameter_checks(int format)
{
    struct bladerf_sync s;
    init(&s, format, 8192);
    struct tx_options options = {0};
    int null_rc = handle_tx_parameters(NULL, &s, &options);
    struct bladerf_metadata metadata = {0};
    metadata.flags = BLADERF_META_FLAG_TX_NOW;
    int now_rc = handle_tx_parameters(&metadata, &s, &options);
    metadata.flags = BLADERF_META_FLAG_TX_BURST_END;
    int end_rc = handle_tx_parameters(&metadata, &s, &options);
    printf("{\"parameters\":true,\"format\":%d,\"null_rc\":%d,"
           "\"NOW_without_START_rc\":%d,\"END_without_START_rc\":%d}\n",
           format, null_rc, now_rc, end_rc);
    destroy(&s);
}

static void update_case(int format)
{
    struct bladerf_sync s;
    init(&s, format, 2048);
    size_t bps = s.stream_config.bytes_per_sample;
    uint8_t reference[64] = {0};
    for (unsigned i = 0; i < 5 * bps; ++i) reference[i] = (uint8_t)(i + 1);
    for (unsigned i = 0; i < 3 * bps; ++i) reference[13 * bps + i] = (uint8_t)(101 + i);
    struct bladerf_metadata metadata = {0};
    metadata.timestamp = 1000000;
    metadata.flags = BLADERF_META_FLAG_TX_BURST_START;
    reset_expectation(reference, 16 * bps, 1000000);
    int first = sync_tx(&s, reference, 5, &metadata, 3000);
    metadata.timestamp = 1000013;
    metadata.flags = BLADERF_META_FLAG_TX_UPDATE_TIMESTAMP | BLADERF_META_FLAG_TX_BURST_END;
    int second = sync_tx(&s, reference + 13 * bps, 3, &metadata, 3000);
    bool ok = first == 0 && second == 0 && seen_bytes >= 16 * bps && !header_errors &&
              !data_errors && !padding_errors && !guard_errors && !s.meta.in_burst;
    printf("{\"update_case\":true,\"format\":%d,\"first_rc\":%d,\"second_rc\":%d,"
           "\"passed\":%s,\"header_errors\":%zu,\"data_errors\":%zu,\"padding_errors\":%zu}\n",
           format, first, second, ok ? "true" : "false", header_errors, data_errors, padding_errors);
    destroy(&s);
}

int main(int argc, char **argv)
{
    if (argc != 2) return 2;
    sc16_wire = fopen(argv[1], "wb");
    if (!sc16_wire) return 2;
    for (int which = 0; which < 2; ++which) {
        int format = which ? BLADERF_FORMAT_SC8_Q7_META : BLADERF_FORMAT_SC16_Q11_META;
        size_t bps = which ? 2 : 4;
        parameter_checks(format);
        update_case(format);
        for (unsigned geometry = 0; geometry < 2; ++geometry) {
            size_t message_size = geometry ? 8192 : 2048;
            unsigned spm = (message_size - 16) / bps;
            unsigned payload = (65536 * bps / message_size) * spm;
            unsigned counts[] = {7, spm - 1, spm, spm + 1,
                                 payload - 1, payload, payload + 1, payload + 17};
            for (unsigned i = 0; i < 8; ++i) run_case(format, message_size, counts[i], false, false);
            run_case(format, message_size, payload + 17, true, false);
        }
    }
    run_case(BLADERF_FORMAT_SC16_Q11_META, 2048, 1017, false, true);
    run_case(BLADERF_FORMAT_SC8_Q7_META, 2048, 1017, false, true);
    run_case(BLADERF_FORMAT_SC8_Q7_META, 2048, 86616000, false, false);
    run_case(BLADERF_FORMAT_SC8_Q7_META, 8192, 86616000, false, false);
    return fclose(sc16_wire) == 0 ? 0 : 2;
}
