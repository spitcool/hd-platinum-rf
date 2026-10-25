// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

namespace platinum {
namespace display {

// One main-task owner, never an ISR or the independent HSPI radio task. The
// controller models the entire peripheral handoff, not only chip-select edges.
class BusIo {
 public:
  virtual ~BusIo() = default;
  virtual void waitDisplay() = 0;
  virtual void deselectDevices() = 0;
  virtual void releaseDisplay() = 0;
  virtual bool initializeDisplay() = 0;
  virtual void endEthernet() = 0;
  virtual bool beginEthernet() = 0;
  virtual void sharedPinInput() = 0;
  virtual void sharedPinOutput() = 0;
};

class BusHandoff {
 public:
  explicit BusHandoff(BusIo& io) : io_(io) {}
  // Call once, immediately after M5.begin has initialized the display. There
  // must be no outstanding display transaction. No panel reset is performed.
  bool begin(bool ethernet) {
    if (started_)
      return available_;
    started_ = true;
    ethernet_ = ethernet;
    available_ = true;
    displayOwned_ = true;
    io_.waitDisplay();
    io_.deselectDevices();
    io_.sharedPinOutput();
    releaseDisplay();
    return available_;
  }

  bool acquireDisplay() {
    if (!available_)
      return false;
    if (displayOwned_)
      return true;
    io_.deselectDevices();
    io_.endEthernet();
    networkReady_ = false;
    if (!io_.initializeDisplay()) {
      // An unsuccessful initialization can have changed pin direction. Fully
      // release it before returning the shared pin to Ethernet's input role.
      io_.releaseDisplay();
      io_.sharedPinInput();
      networkReady_ = io_.beginEthernet();
      available_ = false;
      return false;
    }
    // The M5GFX bus sets MISO=35 during initialization, overriding D/C's output
    // mode. Its cached APB clock can skip restoring that mode on later frames.
    io_.sharedPinOutput();
    displayOwned_ = true;
    return true;
  }

  void releaseDisplay() {
    if (!available_ || !displayOwned_)
      return;
    io_.waitDisplay();
    if (!ethernet_)
      return;
    io_.deselectDevices();
    io_.releaseDisplay();
    io_.sharedPinInput();
    displayOwned_ = false;
    networkReady_ = io_.beginEthernet();
    if (!networkReady_) {
      io_.endEthernet();
      io_.sharedPinInput();
      available_ = false;
    }
  }

  bool available() const {
    return available_;
  }
  bool networkReady() const {
    return started_ && (!ethernet_ || networkReady_);
  }
  bool displayOwned() const {
    return displayOwned_;
  }

 private:
  BusIo& io_;
  bool started_ = false;
  bool ethernet_ = false;
  bool available_ = false;
  bool displayOwned_ = false;
  bool networkReady_ = false;
};

#ifdef ARDUINO
class ArduinoBusIo final : public BusIo {
 public:
  void waitDisplay() override;
  void deselectDevices() override;
  void releaseDisplay() override;
  bool initializeDisplay() override;
  void endEthernet() override;
  bool beginEthernet() override;
  void sharedPinInput() override;
  void sharedPinOutput() override;
};

class ArduinoDisplayBus {
 public:
  ArduinoDisplayBus() : handoff_(io_) {}
  bool begin(bool ethernet);
  bool acquireDisplay() {
    return handoff_.acquireDisplay();
  }
  void releaseDisplay() {
    handoff_.releaseDisplay();
  }
  bool available() const {
    return handoff_.available();
  }
  bool networkReady() const {
    return initialized_ && handoff_.networkReady();
  }

 private:
  ArduinoBusIo io_;
  BusHandoff handoff_;
  bool initialized_ = false;
};
#endif

}  // namespace display
}  // namespace platinum
