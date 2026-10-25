// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include "display_bus.h"

#include <cassert>
#include <string>
#include <vector>

using namespace platinum::display;
struct FakeBus : BusIo {
  std::vector<std::string> events;
  bool displayResult = true, ethernetResult = true;
  bool ethernetActive = false, displayActive = true, devicesDeselected = true;
  bool output = true;
  void waitDisplay() override {
    assert(displayActive);
    events.push_back("wait");
  }
  void deselectDevices() override {
    devicesDeselected = true;
    events.push_back("deselect");
  }
  void releaseDisplay() override {
    displayActive = false;
    events.push_back("release-display");
  }
  bool initializeDisplay() override {
    assert(!ethernetActive && devicesDeselected);
    events.push_back("init-display");
    displayActive = displayResult;
    output = false;  // Match M5GFX SPI init reassigning shared pin as MISO.
    return displayResult;
  }
  void endEthernet() override {
    ethernetActive = false;
    events.push_back("end-ethernet");
  }
  bool beginEthernet() override {
    assert(!displayActive && !output && devicesDeselected);
    events.push_back("begin-ethernet");
    ethernetActive = ethernetResult;
    return ethernetResult;
  }
  void sharedPinInput() override {
    output = false;
    events.push_back("input");
  }
  void sharedPinOutput() override {
    assert(!ethernetActive && devicesDeselected);
    output = true;
    events.push_back("output");
  }
};
int main() {
  {
    FakeBus io;
    BusHandoff bus(io);
    assert(!bus.acquireDisplay());
    assert(bus.begin(true));
    assert((io.events == std::vector<std::string>{"wait", "deselect", "output", "wait", "deselect",
                                                  "release-display", "input", "begin-ethernet"}));
    assert(bus.networkReady() && !bus.displayOwned());
    io.events.clear();
    assert(bus.acquireDisplay());
    assert((io.events ==
            std::vector<std::string>{"deselect", "end-ethernet", "init-display", "output"}));
    assert(!bus.networkReady() && bus.displayOwned() && io.output);
    // Balanced repeated acquisitions never allocate or initialize again.
    io.events.clear();
    assert(bus.acquireDisplay());
    assert(io.events.empty());
    bus.releaseDisplay();
    assert((io.events == std::vector<std::string>{"wait", "deselect", "release-display", "input",
                                                  "begin-ethernet"}));
    assert(bus.networkReady() && !io.output);
    io.events.clear();
    bus.releaseDisplay();
    assert(io.events.empty());
    for (unsigned i = 0; i < 1000; ++i) {
      assert(bus.acquireDisplay());
      assert(io.output && !io.ethernetActive);
      bus.releaseDisplay();
      assert(!io.output && io.ethernetActive && !io.displayActive);
    }
  }
  {
    FakeBus io;
    BusHandoff bus(io);
    assert(bus.begin(false));
    io.events.clear();
    for (unsigned i = 0; i < 10; ++i) {
      assert(bus.acquireDisplay());
      bus.releaseDisplay();
    }
    assert(io.events == std::vector<std::string>(10, "wait"));
    assert(io.displayActive && !io.ethernetActive && io.output);
  }
  {
    FakeBus io;
    BusHandoff bus(io);
    assert(bus.begin(true));
    io.displayResult = false;
    io.events.clear();
    assert(!bus.acquireDisplay());
    assert((io.events == std::vector<std::string>{"deselect", "end-ethernet", "init-display",
                                                  "release-display", "input", "begin-ethernet"}));
    assert(!bus.available() && bus.networkReady() && !io.output);
    io.events.clear();
    assert(!bus.acquireDisplay());
    bus.releaseDisplay();
    assert(io.events.empty());
  }
  {
    FakeBus io;
    io.ethernetResult = false;
    BusHandoff bus(io);
    assert(!bus.begin(true));
    assert(!bus.available() && !bus.networkReady() && !io.output && !io.ethernetActive);
  }
}
