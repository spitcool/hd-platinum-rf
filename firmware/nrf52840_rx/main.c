/* SPDX-License-Identifier: GPL-2.0-or-later */
#include "capture.h"
#include "registers.h"

volatile struct capture_control capture_control;
volatile struct capture_record capture_records[CAPTURE_RECORD_CAPACITY];
static volatile uint8_t dma_payload[8] __attribute__((aligned(4)));
static uint32_t run_duration_us;
static volatile uint32_t stop_requested;

static void barrier(void) { __asm__ volatile ("dmb" ::: "memory"); }
static uint32_t now_us(void) { TIMER_CAPTURE(4) = 1; return TIMER_CC(4); }

static void timer_initialize(void)
{
    TIMER(TIMER_STOP) = 1;
    TIMER(TIMER_INTENCLR) = UINT32_MAX;
    TIMER(TIMER_SHORTS) = 0;
    TIMER(TIMER_MODE) = 0;       /* timer, not counter */
    TIMER(TIMER_BITMODE) = 3;    /* 32 bits */
    TIMER(TIMER_PRESCALER) = 4;  /* 16 MHz / 16 = 1 MHz */
    for (unsigned i = 0; i < 6; ++i) TIMER_COMPARE(i) = 0;
    TIMER(TIMER_CLEAR) = 1;
}

static void stop_routes(void)
{
    PPI(PPI_CHENCLR) = UINT32_MAX;
    RADIO(RADIO_INTENCLR) = UINT32_MAX;
    RADIO(RADIO_SHORTS) = 0;
    TIMER(TIMER_INTENCLR) = UINT32_MAX;
    NVIC_ICER = RADIO_IRQ_MASK | TIMER_IRQ_MASK;
    NVIC_ICPR = RADIO_IRQ_MASK | TIMER_IRQ_MASK;
}

static void fail(enum capture_error error)
{
    __asm__ volatile ("cpsid i" ::: "memory");
    stop_routes();
    RADIO(RADIO_POWER) = 0;
    TIMER(TIMER_STOP) = 1;
    capture_control.error = error;
    capture_control.stop_reason = CAPTURE_STOP_ERROR;
    capture_control.radio_state = RADIO(RADIO_STATE);
    barrier();
    capture_control.state = CAPTURE_ERROR;
}

static void finish_capture(void)
{
    /* Called only after the radio has reached DISABLED. No DMA can still write. */
    stop_routes();
    capture_control.stop_us = now_us();
    TIMER(TIMER_STOP) = 1;
    capture_control.partial_at_stop = (RADIO(RADIO_ADDRESS) != 0 && RADIO(RADIO_END) == 0);
    capture_control.radio_state = RADIO(RADIO_STATE);
    RADIO(RADIO_POWER) = 0;
    barrier();
    capture_control.state = CAPTURE_DONE;
}

static void request_stop(enum capture_stop_reason reason)
{
    if (capture_control.stop_reason == CAPTURE_STOP_NONE) capture_control.stop_reason = reason;
    stop_requested = 1;
    /* Do not repeat DISABLE once the receiver is already disabling/disabled. */
    uint32_t state = RADIO(RADIO_STATE);
    if (state >= 1 && state <= 3) RADIO(RADIO_DISABLE) = 1;
}

static void receive_next(void)
{
    RADIO(RADIO_READY) = 0;
    RADIO(RADIO_ADDRESS) = 0;
    RADIO(RADIO_END) = 0;
    RADIO(RADIO_DISABLED) = 0;
    RADIO(RADIO_RSSIEND) = 0;
    RADIO(RADIO_CRCOK) = 0;
    RADIO(RADIO_CRCERROR) = 0;
    RADIO(RADIO_PACKETPTR) = (uint32_t)(uintptr_t)dma_payload;
    barrier();
    if (stop_requested || TIMER_COMPARE(2) || now_us() >= run_duration_us) {
        request_stop(CAPTURE_STOP_DEADLINE);
        return;
    }
    ++capture_control.rx_attempt_count;
    RADIO(RADIO_RXEN) = 1;
    /* Close the race where the hardware deadline DISABLE occurred immediately
     * before RXEN. Once RXEN has been written, a later deadline or this second
     * test always leaves DISABLE as the last task. This can never schedule TX.
     */
    if (TIMER_COMPARE(2)) request_stop(CAPTURE_STOP_DEADLINE);
}

void radio_irq_handler(void)
{
    ++capture_control.radio_irq_count;
    if (!RADIO(RADIO_DISABLED)) return;
    RADIO(RADIO_DISABLED) = 0;
    if (capture_control.state != CAPTURE_RUNNING) return;
    if (RADIO(RADIO_END)) {
        struct capture_record record = {0};
        record.address_us = TIMER_CC(0);
        record.end_us = TIMER_CC(1);
        record.ready_us = TIMER_CC(3);
        record.rx_crc = RADIO(RADIO_RXCRC);
        record.crc_status = (uint8_t)RADIO(RADIO_CRCSTATUS);
        record.rssi_sample = (uint8_t)RADIO(RADIO_RSSISAMPLE);
        record.rxmatch = (uint8_t)RADIO(RADIO_RXMATCH);
        if (RADIO(RADIO_ADDRESS)) record.flags |= CAPTURE_RECORD_ADDRESS;
        if (RADIO(RADIO_RSSIEND)) record.flags |= CAPTURE_RECORD_RSSI;
        barrier();
        for (unsigned i = 0; i < 5; ++i) record.payload[i] = dma_payload[i];
        (void)capture_log_append(&capture_control, capture_records, &record);
    }
    if (capture_control.stop_reason == CAPTURE_STOP_CAPACITY) {
        request_stop(CAPTURE_STOP_CAPACITY);
    } else if (TIMER_COMPARE(2) || now_us() >= run_duration_us) {
        request_stop(CAPTURE_STOP_DEADLINE);
    }
    if (stop_requested) finish_capture();
    else receive_next();
}

void timer_irq_handler(void)
{
    if (TIMER_COMPARE(2) && capture_control.state == CAPTURE_RUNNING) {
        /* Keep the event latched so receive_next cannot miss the cutoff. */
        TIMER(TIMER_INTENCLR) = UINT32_C(1) << 18;
        request_stop(CAPTURE_STOP_DEADLINE);
    }
}

void unexpected_irq_handler(void)
{
    fail(CAPTURE_ERROR_EXCEPTION);
    for (;;) __asm__ volatile ("nop");
}

static void set_ppi(unsigned channel, uint32_t event, uint32_t task)
{
    PPI(PPI_CH0_EEP + 8u * channel) = event;
    PPI(PPI_CH0_TEP + 8u * channel) = task;
    PPI(PPI_FORK0_TEP + 4u * channel) = 0;
}

static void start_capture(void)
{
    if (!capture_config_valid(&capture_control)) { fail(CAPTURE_ERROR_CONFIG); return; }
    uint32_t channel = capture_control.channel;
    run_duration_us = capture_control.duration_us;
    capture_control.command = 0;
    timer_initialize();
    RADIO(RADIO_MODE) = 1;           /* Nordic proprietary 2 Mbps, not BLE */
    RADIO(RADIO_PCNF0) = 0;          /* no S0/LENGTH/S1; 8-bit preamble */
    RADIO(RADIO_PCNF1) = 0x01020505; /* big endian, no whitening, 3+5 bytes */
    RADIO(RADIO_BASE0) = 0xe7e70000;
    RADIO(RADIO_BASE1) = 0;
    RADIO(RADIO_PREFIX0) = 0xe7;
    RADIO(RADIO_PREFIX1) = 0;
    RADIO(RADIO_RXADDRESSES) = 1;
    RADIO(RADIO_CRCCNF) = 2;         /* CRC16 includes address */
    RADIO(RADIO_CRCPOLY) = 0x11021;
    RADIO(RADIO_CRCINIT) = 0xffff;
    RADIO(RADIO_FREQUENCY) = channel;
    RADIO(RADIO_MODECNF0) = 0x201;   /* fast ramp-up, idle TX center (unused) */
    RADIO(RADIO_SHORTS) = (1u << 0) | (1u << 1) | (1u << 4) | (1u << 8);
    /* READY->START, END->DISABLE, ADDRESS->RSSISTART, DISABLED->RSSISTOP */
    RADIO(RADIO_INTENSET) = 1u << 4; /* DISABLED only */
    set_ppi(0, RADIO_BASE + RADIO_ADDRESS, TIMER_BASE + TIMER_CAPTURE0);
    set_ppi(1, RADIO_BASE + RADIO_END, TIMER_BASE + TIMER_CAPTURE0 + 4);
    set_ppi(2, RADIO_BASE + RADIO_READY, TIMER_BASE + TIMER_CAPTURE0 + 12);
    set_ppi(3, TIMER_BASE + TIMER_COMPARE0 + 8, RADIO_BASE + RADIO_DISABLE);
    TIMER_CC(2) = run_duration_us;
    TIMER(TIMER_INTENSET) = UINT32_C(1) << 18;
    PPI(PPI_CHENSET) = 0xf;
    /* Both IRQs have equal priority: neither observes a half-copied record. */
    REG32(0xe000e400) = 0x00004000;  /* RADIO priority byte1 */
    REG32(0xe000e418) = 0x40000000;  /* TIMER4 priority byte27 */
    NVIC_ICPR = RADIO_IRQ_MASK | TIMER_IRQ_MASK;
    NVIC_ISER = RADIO_IRQ_MASK | TIMER_IRQ_MASK;
    capture_control.state = CAPTURE_RUNNING;
    TIMER(TIMER_START) = 1;
    receive_next();
    __asm__ volatile ("cpsie i" ::: "memory");
}

void firmware_main(void)
{
    /* Startup already masked IRQs, disabled every PPI channel and powered RADIO
     * off before clearing BSS. Host reset-and-halt remains a prerequisite.
     */
    REG32(0xe000e010) = 0; /* SysTick CTRL */
    REG32(0xe000e018) = 0; /* SysTick VAL */
    REG32(0xe000ed04) = (1u << 27) | (1u << 25); /* clear PendSV / SysTick */
    for (unsigned i = 0; i < 2; ++i) {
        REG32(0xe000e180 + 4u * i) = UINT32_MAX;
        REG32(0xe000e280 + 4u * i) = UINT32_MAX;
    }
    for (unsigned i = 0; i < 20; ++i) PPI(PPI_FORK0_TEP + 4u * i) = 0;
    for (unsigned i = 0; i < 6; ++i) PPI(0x800 + 4u * i) = 0;
    capture_log_init(&capture_control);
    capture_control.records_address = (uint32_t)(uintptr_t)capture_records;
    capture_control.ficr_part = REG32(0x10000100);
    capture_control.ficr_variant = REG32(0x10000104);
    capture_control.ficr_package = REG32(0x10000108);
    capture_control.ficr_ram_kib = REG32(0x1000010c);
    capture_control.ficr_flash_kib = REG32(0x10000110);
    capture_control.ficr_id0 = REG32(0x10000130);
    capture_control.ficr_id1 = REG32(0x10000134);
    capture_control.ficr_id2 = REG32(0x10000138);
    capture_control.resetreas = REG32(0x40000400);
    if (capture_control.ficr_part != 0x52840 ||
        capture_control.ficr_variant != 0x41414630 ||
        capture_control.ficr_id0 != 8 || capture_control.ficr_id1 != 5 ||
        capture_control.ficr_ram_kib != 256 || capture_control.ficr_flash_kib != 1024) {
        fail(CAPTURE_ERROR_CHIP);
        return;
    }
    if (REG32(0x40010400) != 0) { fail(CAPTURE_ERROR_WATCHDOG); return; }
    RADIO(RADIO_POWER) = 1;
    if (RADIO(RADIO_STATE) != 0) { fail(CAPTURE_ERROR_RADIO); return; }
    timer_initialize();
    TIMER(TIMER_START) = 1;
    CLOCK(0x308) = UINT32_MAX; /* no inherited clock interrupt */
    CLOCK(0x10c) = 0;        /* DONE: anomaly36 reset residue */
    CLOCK(0x110) = 0;        /* CTTO */
    CLOCK(0x538) = 0;        /* CTIV */
    CLOCK(0x100) = 0;        /* HFCLKSTARTED */
    if ((CLOCK(0x40c) & 0x10001) != 0x10001) {
        CLOCK(0x000) = 1;    /* HFCLKSTART: crystal */
        while ((CLOCK(0x40c) & 0x10001) != 0x10001) {
            if (now_us() >= 500000) { fail(CAPTURE_ERROR_CLOCK); return; }
        }
    }
    capture_control.hfclkstat = CLOCK(0x40c);
    TIMER(TIMER_STOP) = 1;
    barrier();
    capture_control.state = CAPTURE_READY;
    /* SWD writes do not necessarily wake WFI. Poll without touching the radio. */
    while (capture_control.command == 0) __asm__ volatile ("nop");
    start_capture();
    while (capture_control.state == CAPTURE_RUNNING) {
        if (stop_requested && RADIO(RADIO_STATE) == 0) {
            __asm__ volatile ("cpsid i" ::: "memory");
            /* Service a completed pending frame before publishing DONE. */
            if (RADIO(RADIO_DISABLED)) radio_irq_handler();
            if (capture_control.state == CAPTURE_RUNNING) finish_capture();
        } else if (now_us() > run_duration_us + 10000) {
            fail(CAPTURE_ERROR_RADIO); /* independent bounded shutdown guard */
        }
    }
    __asm__ volatile ("cpsid i" ::: "memory");
}
