// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include "display_bus.h"
#ifdef ARDUINO
#include <Arduino.h>
#include <M5Unified.h>
#include <SPI.h>

namespace platinum {
namespace display {
void ArduinoBusIo::waitDisplay() {
  // Caller balances any explicit startWrite. waitDMA ensures both normal and
  // sprite/DMA rendering complete before peripheral ownership changes.
  M5.Display.waitDMA();
  M5.Display.endWrite();
}
void ArduinoBusIo::deselectDevices() {
  // Set output latches before direction to avoid a low CS transient. W5500
  // releases MISO before GPIO35 may become the display D/C output.
  for (int pin : {9, 3, 4}) {
    digitalWrite(pin, HIGH);
    pinMode(pin, OUTPUT);
  }
  delayMicroseconds(1);
}
void ArduinoBusIo::releaseDisplay() {
  M5.Display.releaseBus();
}
bool ArduinoBusIo::initializeDisplay() {
  // Reinitialize only the existing bus object. Calling Display.begin/init here
  // would also reset/reinitialize the panel and could erase its displayed UI.
  auto* panel = M5.Display.panel();
  return panel && panel->getBus() && panel->getBus()->init();
}
void ArduinoBusIo::endEthernet() {
  SPI.end();
}
bool ArduinoBusIo::beginEthernet() {
  SPI.begin(36, 35, 37, -1);
  return SPI.bus() != nullptr;
}
void ArduinoBusIo::sharedPinInput() {
  pinMode(35, INPUT);
}
void ArduinoBusIo::sharedPinOutput() {
  digitalWrite(35, HIGH);
  pinMode(35, OUTPUT);
}
bool ArduinoDisplayBus::begin(bool ethernet) {
  // This adapter is deliberately specific to the CoreS3/CoreS3 SE shared pin
  // map. Never silently apply it to another board selected by auto-detection.
  const auto board = M5.getBoard();
  if (board != m5::board_t::board_M5StackCoreS3 && board != m5::board_t::board_M5StackCoreS3SE)
    return false;
  initialized_ = true;
  return handoff_.begin(ethernet);
}
}  // namespace display
}  // namespace platinum
#endif
