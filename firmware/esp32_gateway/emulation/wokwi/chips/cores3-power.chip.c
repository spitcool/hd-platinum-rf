// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
// CoreS3 SE: AXP2101 (0x34) and AW9523B (0x58) on SDA12/SCL11.
// Register-level peripherals, used by the unmodified M5GFX/M5Unified drivers.
// References: AXP2101 datasheet v1.0, AW9523B datasheet v1.1,
// https://docs.wokwi.com/chips-api/i2c
// Analog fixtures: USB 5 V, VSYS 3.3 V, battery absent, TS input 0 V.
// Analog ramp times, LED PWM and the AW's 8 us input filter are not modeled.

#include <stdbool.h>
#include <stdint.h>
#include <string.h>

#ifndef CORES3_POWER_TEST
#include "wokwi-api.h"
#endif

enum { AXP_ADDRESS = 0x34, AW_ADDRESS = 0x58 };

typedef struct {
  uint8_t axp[256];
  uint8_t aw[256];
  uint8_t external[2];
  uint8_t pending[2];
} power_model_t;

typedef struct {
  power_model_t *model;
  uint8_t address;
  uint8_t pointer;
  bool expect_pointer;
} endpoint_t;

static void aw_reset(power_model_t *m) {
  memset(m->aw, 0, sizeof(m->aw));
  m->aw[0x10] = 0x23;
  m->aw[0x12] = m->aw[0x13] = 0xff;
  m->pending[0] = m->pending[1] = 0;
  // AD1=AD0=0: both output latches and direction registers reset to zero.
}

static void axp_system_reset(power_model_t *m) {
  m->axp[0x10] = 0x30;
  m->axp[0x40] = 0xff;
  m->axp[0x41] = 0xfc;
  m->axp[0x42] = 0x5f;
  m->axp[0x48] = m->axp[0x49] = m->axp[0x4a] = 0;
  // These registers have board-programmed eFuse defaults, not universal
  // datasheet constants. Supply DCDC1; leave optional rails off until the
  // real board driver configures them. Do not emulate eFuse programming.
  memset(&m->axp[0x80], 0, 7);
  m->axp[0x80] = 1;
  m->axp[0x82] = 0x12; // DCDC1 3.3 V (1.5 V + 18 * 100 mV).
  memset(&m->axp[0x90], 0, 11);
}

static void power_reset(power_model_t *m) {
  memset(m, 0, sizeof(*m));
  m->external[0] = m->external[1] = 0xff;
  aw_reset(m);
  axp_system_reset(m);
  m->axp[0x00] = 0x20; // VBUS good; battery absent.
  m->axp[0x03] = 0x4a;
  m->axp[0x13] = 0x03;
  m->axp[0x14] = 0x65;
  m->axp[0x15] = 0x06;
  m->axp[0x16] = 0x01;
  m->axp[0x18] = 0x0a;
  m->axp[0x23] = 0x3f;
  m->axp[0x26] = 0x08;
  m->axp[0x38] = 0x13; m->axp[0x39] = 0x88; // VBUS ADC: 5000 mV.
  m->axp[0x3a] = 0x0c; m->axp[0x3b] = 0xe4; // VSYS ADC: 3300 mV.
  m->axp[0x61] = 0x05;
  m->axp[0x64] = 0x03;
  m->axp[0x67] = 0xd6;
  m->axp[0x6a] = 0x03;
}

static uint8_t aw_inputs(const power_model_t *m, unsigned port) {
  uint8_t result = 0;
  for (unsigned bit = 0; bit < 8; ++bit) {
    const uint8_t mask = (uint8_t)(1u << bit);
    bool high;
    if (!(m->aw[0x12 + port] & mask)) {
      // LED mode is a current sink. This digital model exposes its steady
      // on/off state; it does not synthesize the analog LED current.
      unsigned dim = port == 0 ? 0x24 + bit :
          (bit < 4 ? 0x20 + bit : 0x28 + bit);
      high = m->aw[dim] == 0 && (m->external[port] & mask);
    } else if (m->aw[0x04 + port] & mask) {
      high = (m->external[port] & mask) != 0;
    } else if (port == 0 && !(m->aw[0x11] & 0x10)) {
      // P0 is open drain until GCR selects push-pull; P1 is push-pull.
      high = (m->aw[0x02] & m->external[0] & mask) != 0;
    } else {
      high = (m->aw[0x02 + port] & mask) != 0;
    }
    if (high) result |= mask;
  }
  return result;
}

static uint8_t aw_irq_mask(const power_model_t *m, unsigned port) {
  return m->aw[0x04 + port] & m->aw[0x12 + port] &
      (uint8_t)~m->aw[0x06 + port];
}

static bool aw_irq_active(const power_model_t *m) {
  return (m->pending[0] & aw_irq_mask(m, 0)) != 0 ||
         (m->pending[1] & aw_irq_mask(m, 1)) != 0;
}

static void aw_external(power_model_t *m, unsigned port, uint8_t levels) {
  const uint8_t before = aw_inputs(m, port);
  m->external[port] = levels;
  m->pending[port] |= (before ^ aw_inputs(m, port)) & aw_irq_mask(m, port);
}

static uint8_t register_read(power_model_t *m, uint8_t address, uint8_t reg) {
  if (address == AW_ADDRESS) {
    if (reg < 2) {
      const uint8_t result = aw_inputs(m, reg);
      m->pending[reg] = 0; // A read clears only this port's interrupt latch.
      return result;
    }
    return m->aw[reg];
  }
  return m->axp[reg];
}

static void register_write(power_model_t *m, uint8_t address,
                           uint8_t reg, uint8_t value) {
  if (address == AW_ADDRESS) {
    if (reg == 0x7f) {
      if (value == 0) aw_reset(m);
      return;
    }
    if ((reg >= 0x02 && reg <= 0x07) ||
        (reg >= 0x11 && reg <= 0x13) ||
        (reg >= 0x20 && reg <= 0x2f)) {
      m->aw[reg] = value;
      // Masked, output, and LED pins cannot keep INTN asserted.
      for (unsigned port = 0; port < 2; ++port)
        m->pending[port] &= aw_irq_mask(m, port);
    }
    return;
  }
  if (reg >= 0x48 && reg <= 0x4a) {
    m->axp[reg] &= (uint8_t)~value; // Write-one-to-clear interrupt status.
  } else if (reg == 0x10 && (value & 2)) {
    axp_system_reset(m); // Software reset is self-clearing, preserves POR data.
  } else if (reg != 0x00 && reg != 0x01 && reg != 0x03 &&
             reg != 0x20 && reg != 0x21 && reg != 0xa4 &&
             !(reg >= 0x34 && reg <= 0x3d)) {
    m->axp[reg] = value;
  }
}

static void endpoint_connect(endpoint_t *ep, bool read) {
  if (!read) ep->expect_pointer = true;
  // Repeated START and STOP preserve the register pointer for random reads.
}

static void endpoint_write(endpoint_t *ep, uint8_t value) {
  if (ep->expect_pointer) {
    ep->pointer = value;
    ep->expect_pointer = false;
  } else {
    register_write(ep->model, ep->address, ep->pointer++, value);
  }
}

static uint8_t endpoint_read(endpoint_t *ep) {
  return register_read(ep->model, ep->address, ep->pointer++);
}

static bool powered(const power_model_t *m) {
  return !(m->axp[0x10] & 1) && (m->axp[0x80] & 1);
}

static bool backlight(const power_model_t *m) {
  return powered(m) && (m->axp[0x90] & 0x80) && (m->axp[0x99] & 0x1f);
}

#ifndef CORES3_POWER_TEST
typedef struct {
  power_model_t model;
  endpoint_t axp, aw;
  pin_t irq, touch_int, lcd_reset, touch_reset, bus_power, usb_power, backlight;
} chip_state_t;

static chip_state_t chip;

static void update_pins(chip_state_t *c) {
  const uint8_t p0 = aw_inputs(&c->model, 0);
  const uint8_t p1 = aw_inputs(&c->model, 1);
  const bool on = powered(&c->model);
  // Release INTN instead of driving it high, so it can share a wired-OR net.
  pin_mode(c->irq, aw_irq_active(&c->model) ? OUTPUT_LOW : INPUT_PULLUP);
  pin_write(c->touch_reset, on && (p0 & 0x01) ? HIGH : LOW);
  pin_write(c->lcd_reset, on && (p1 & 0x02) ? HIGH : LOW);
  pin_write(c->bus_power, on && (p1 & 0x80) && (p0 & 0x02) ? HIGH : LOW);
  pin_write(c->usb_power, on && (p1 & 0x80) && (p0 & 0x20) ? HIGH : LOW);
  pin_write(c->backlight, backlight(&c->model) ? HIGH : LOW);
}

static bool on_connect(void *data, uint32_t address, bool read) {
  endpoint_t *ep = data;
  if (address != ep->address) return false;
  endpoint_connect(ep, read);
  return true;
}

static bool on_write(void *data, uint8_t value) {
  endpoint_write(data, value);
  update_pins(&chip);
  return true;
}

static uint8_t on_read(void *data) {
  const uint8_t value = endpoint_read(data);
  update_pins(&chip);
  return value;
}

static void on_touch_interrupt(void *data, pin_t pin, uint32_t value) {
  (void)pin;
  chip_state_t *c = data;
  const uint8_t levels = (c->model.external[1] & (uint8_t)~0x04) |
      (value ? 0x04 : 0);
  aw_external(&c->model, 1, levels);
  update_pins(c);
}

void chip_init(void) {
  power_reset(&chip.model);
  chip.axp = (endpoint_t){ .model = &chip.model, .address = AXP_ADDRESS };
  chip.aw = (endpoint_t){ .model = &chip.model, .address = AW_ADDRESS };
  const pin_t sda = pin_init("SDA", INPUT_PULLUP);
  const pin_t scl = pin_init("SCL", INPUT_PULLUP);
  chip.irq = pin_init("AW_INTN", INPUT_PULLUP);
  chip.touch_int = pin_init("TOUCH_INT", INPUT_PULLUP);
  chip.lcd_reset = pin_init("LCD_RESET", OUTPUT_LOW);
  chip.touch_reset = pin_init("TOUCH_RESET", OUTPUT_LOW);
  chip.bus_power = pin_init("BUS_POWER", OUTPUT_LOW);
  chip.usb_power = pin_init("USB_POWER", OUTPUT_LOW);
  chip.backlight = pin_init("BACKLIGHT", OUTPUT_LOW);

  i2c_config_t axp = { .address = AXP_ADDRESS, .sda = sda, .scl = scl,
    .connect = on_connect, .read = on_read, .write = on_write,
    .user_data = &chip.axp };
  i2c_config_t aw = { .address = AW_ADDRESS, .sda = sda, .scl = scl,
    .connect = on_connect, .read = on_read, .write = on_write,
    .user_data = &chip.aw };
  i2c_init(&axp);
  i2c_init(&aw);
  pin_watch_config_t touch = { .edge = BOTH,
    .pin_change = on_touch_interrupt, .user_data = &chip };
  pin_watch(chip.touch_int, &touch);
  on_touch_interrupt(&chip, chip.touch_int, pin_read(chip.touch_int));
}
#else
// Standalone register tests, without Wokwi or a firmware-driver substitute:
// cc -std=c11 -Wall -Wextra -Werror -DCORES3_POWER_TEST \
//   cores3-power.chip.c -o /tmp/cores3-power-test && /tmp/cores3-power-test
#include <assert.h>
#include <stdio.h>

int main(void) {
  power_model_t m;
  power_reset(&m);
  assert(register_read(&m, AXP_ADDRESS, 3) == 0x4a);
  assert(register_read(&m, AW_ADDRESS, 0x10) == 0x23);
  assert(m.axp[0x00] == 0x20 && m.axp[0x36] == 0 && m.axp[0x37] == 0);
  assert(((m.axp[0x38] & 0x3f) << 8 | m.axp[0x39]) == 5000);
  assert(m.aw[2] == 0 && m.aw[3] == 0 && m.aw[4] == 0 && m.aw[5] == 0);
  register_write(&m, AW_ADDRESS, 0x10, 0);
  register_write(&m, AXP_ADDRESS, 3, 0);
  register_write(&m, AXP_ADDRESS, 0x38, 0);
  assert(m.aw[0x10] == 0x23 && m.axp[3] == 0x4a && m.axp[0x38] == 0x13);

  // The driver's two-byte AW transaction must retain both output latches.
  endpoint_t ep = { .model = &m, .address = AW_ADDRESS };
  endpoint_connect(&ep, false);
  endpoint_write(&ep, 2); endpoint_write(&ep, 0x27); endpoint_write(&ep, 0x83);
  endpoint_connect(&ep, false); endpoint_write(&ep, 2);
  endpoint_connect(&ep, true);
  assert(endpoint_read(&ep) == 0x27 && endpoint_read(&ep) == 0x83);
  register_write(&m, AW_ADDRESS, 4, 0x18);
  register_write(&m, AW_ADDRESS, 5, 0x0c);
  register_write(&m, AW_ADDRESS, 0x11, 0x10);
  assert(aw_inputs(&m, 0) == 0x3f && aw_inputs(&m, 1) == 0x8f);

  // Touch assertion and release latch an interrupt; reading the other port
  // cannot acknowledge it. Masked, output and LED pins cannot interrupt.
  aw_external(&m, 1, 0xfb);
  assert(aw_irq_active(&m) && !(aw_inputs(&m, 1) & 4));
  register_read(&m, AW_ADDRESS, 0);
  assert(aw_irq_active(&m));
  register_read(&m, AW_ADDRESS, 1);
  assert(!aw_irq_active(&m));
  aw_external(&m, 1, 0xff);
  assert(aw_irq_active(&m));
  register_write(&m, AW_ADDRESS, 7, 4);
  assert(!aw_irq_active(&m));
  aw_external(&m, 1, 0xfb);
  assert(!aw_irq_active(&m));
  register_write(&m, AW_ADDRESS, 7, 0);
  register_write(&m, AW_ADDRESS, 5, 8);
  aw_external(&m, 1, 0xff);
  assert(!aw_irq_active(&m));
  register_write(&m, AW_ADDRESS, 5, 0x0c);
  register_write(&m, AW_ADDRESS, 0x13, 0xfb);
  aw_external(&m, 1, 0xfb);
  assert(!aw_irq_active(&m));

  m.axp[0x49] = 0x0c;
  register_write(&m, AXP_ADDRESS, 0x49, 4);
  assert(m.axp[0x49] == 8);
  register_write(&m, AXP_ADDRESS, 0x49, 0);
  assert(m.axp[0x49] == 8);
  register_write(&m, AXP_ADDRESS, 0x90, 0xbf);
  register_write(&m, AXP_ADDRESS, 0x99, 24);
  assert(backlight(&m));
  register_write(&m, AXP_ADDRESS, 0x10, 0x31);
  assert(!powered(&m) && !backlight(&m));
  register_write(&m, AXP_ADDRESS, 0x10, 0x32);
  assert(powered(&m) && !backlight(&m) && m.axp[0x49] == 0);
  assert(m.axp[0x38] == 0x13 && m.axp[0x23] == 0x3f);
  register_write(&m, AW_ADDRESS, 0x7f, 1);
  assert(m.aw[2] == 0x27);
  register_write(&m, AW_ADDRESS, 0x7f, 0);
  assert(m.aw[2] == 0 && m.aw[5] == 0 && m.aw[0x13] == 0xff);
  assert(m.axp[3] == 0x4a && !aw_irq_active(&m));
  puts("CoreS3 power register tests passed");
  return 0;
}
#endif
