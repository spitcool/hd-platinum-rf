// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <vector>

#include "gateway_radio.h"

using namespace platinum::radio;

class FakeIo final : public Io {
 public:
  std::array<std::array<uint8_t, 5>, 32> registers{};
  std::vector<std::vector<uint8_t>> payloads;
  std::vector<uint32_t> pulses;
  uint32_t time = 0;
  uint8_t completion = 0x10;  // Missing ACK, zero retries.
  uint8_t status = 0;
  int corrupt_register = -1;
  uint32_t delay_overshoot = 0;
  bool started = false, ended = false, ce = false;

  bool begin() override {
    started = true;
    registers[0x17][0] = 0x11;
    return true;
  }
  void end() override {
    ended = true;
  }
  void chipEnable(bool high) override {
    ce = high;
    if (high) {
      pulses.push_back(time);
      status = completion;
    }
  }
  uint8_t transfer(uint8_t instruction, const uint8_t* tx, uint8_t* rx, size_t size) override {
    if ((instruction & 0xe0) == 0x20) {
      const uint8_t reg = instruction & 0x1f;
      if (reg == 7)
        status &= ~tx[0];
      else
        std::copy(tx, tx + size, registers[reg].begin());
    } else if (instruction < 0x20) {
      std::copy(registers[instruction].begin(), registers[instruction].begin() + size, rx);
      if (instruction == corrupt_register && size)
        rx[0] ^= 1;
    } else if (instruction == 0xa0) {
      payloads.emplace_back(tx, tx + size);
    }
    return status;
  }
  uint32_t micros() override {
    return time;
  }
  void delayUs(uint32_t duration) override {
    time += duration + delay_overshoot;
  }
};

Command command() {
  Command value;
  value.room_id = {{0x12, 0x34}};
  value.mask = 0x80;
  value.position = 0xff;
  value.operation_enabled = true;
  return value;
}

void payload_contract() {
  Payload payload;
  auto value = command();
  assert(encodeCommand(value, payload));
  const std::array<uint8_t, 12> expected = {
      {1, 10, 2, 0x34, 0x12, 0x34, 4, 0x80, 0xff, 0, 1, 0x9f}};
  assert(payload.size == 12 && payload.bytes == expected);
  value.mask = 1;
  value.operation = Operation::Sync;
  assert(encodeCommand(value, payload));
  assert(payload.bytes[6] == 1 && payload.bytes[8] == 0 && payload.bytes[10] == 3 &&
         payload.bytes[11] == 0xe6);
  value.operation = Operation::Jog;
  assert(encodeCommand(value, payload));
  assert(payload.bytes[6] == 12 && payload.bytes[8] == 1 && payload.bytes[10] == 1 &&
         payload.bytes[11] == 0xe8);
  for (uint8_t mask : {0, 3, 0xff}) {
    value.mask = mask;
    assert(!encodeCommand(value, payload) && payload.size == 0);
  }
  value.mask = 1;
  value.operation = static_cast<Operation>(255);
  assert(!encodeCommand(value, payload));
  assert(encodeSequence(255, 4, payload));
  assert(payload.size == 9 && payload.bytes[4] == 1 && payload.bytes[5] == 255 &&
         payload.bytes[8] == 0x3e);
  assert(encodeSequence(256, 4, payload));
  assert(payload.bytes[4] == 1 && payload.bytes[5] == 0 && payload.bytes[8] == 0xc1);
  assert(encodeSequence(65535, 0, payload));
  assert(payload.bytes[4] == 1 && payload.bytes[5] == 255 && payload.bytes[8] == 0x3a);
  assert(!encodeSequence(0, 5, payload));
}

void gates_and_configuration() {
  FakeIo io;
  Radio radio(io);
  Policy policy;
  assert(radio.begin(policy) == ResultCode::Ready);
  assert(io.pulses.empty() && !io.ce);
  assert(radio.transmit(command(), 1).code == ResultCode::Disabled);
  policy.enabled = true;
  assert(radio.begin(policy) == ResultCode::Ready);
  assert(radio.transmit(command(), 1).code == ResultCode::Unqualified);
  policy.qualified = true;
  policy.power = 2;
  assert(radio.begin(policy) == ResultCode::Ready);
  auto denied = command();
  denied.operation_enabled = false;
  assert(radio.transmit(denied, 1).code == ResultCode::OperationDisabled);
  assert(io.pulses.empty());
  assert(io.registers[0][0] == 0x0e && io.registers[1][0] == 1 && io.registers[3][0] == 1 &&
         io.registers[4][0] == 0 && io.registers[5][0] == 40 && io.registers[6][0] == 0x24 &&
         io.registers[0x1c][0] == 1 && io.registers[0x1d][0] == 4);
  policy.recipe = Recipe::OriginalRegisterExperiment;
  assert(radio.begin(policy) == ResultCode::Ready && io.registers[1][0] == 0);
  policy.power = 3;
  assert(radio.begin(policy) == ResultCode::InvalidPolicy && !radio.ready());
  assert(io.pulses.empty());
  policy.power = 0;
  io.corrupt_register = 5;
  assert(radio.begin(policy) == ResultCode::RegisterMismatch);
  assert(!radio.ready() && io.ended && !io.ce && io.registers[0][0] == 0x0c);
}

void bounded_transmission() {
  for (uint32_t start : {uint32_t{0}, uint32_t{0xfffff000}}) {
    FakeIo io;
    io.time = start;
    Radio radio(io);
    Policy policy;
    policy.enabled = policy.qualified = true;
    assert(radio.begin(policy) == ResultCode::Ready);
    const uint32_t began = io.time;
    const Result result = radio.transmit(command(), 256);
    assert(result.code == ResultCode::Submitted && result.frames_submitted == 10 &&
           result.missing_acks == 10 && io.pulses.size() == 10 && !io.ce);
    assert(io.time - began == kBurstDurationUs);
    assert(io.payloads.size() == 10);
    for (size_t i = 0; i < 10; ++i) {
      assert(io.pulses[i] - began == (kPreambleEighthUs[i] + 7) / 8 - 130);
      assert(io.payloads[i].size() == ((i & 1) ? 9u : 12u));
      if (i & 1) {
        assert(io.payloads[i][4] == 1 && io.payloads[i][5] == 0 && io.payloads[i][6] == 4 - i / 2);
      }
    }
    radio.shutdown();
    assert(!radio.ready() && io.ended && !io.ce && io.registers[0][0] == 0x0c);
  }
  FakeIo io;
  Radio radio(io);
  Policy policy;
  policy.enabled = policy.qualified = true;
  assert(radio.begin(policy) == ResultCode::Ready);
  io.completion = 0;
  const uint32_t before = io.time;
  const auto timeout = radio.transmit(command(), 42);
  assert(timeout.code == ResultCode::Timeout && timeout.frames_submitted == 1);
  assert(io.time - before < 15000 && !radio.ready() && !io.ce);
  assert(radio.transmit(command(), 43).code == ResultCode::NotReady);
  assert(io.pulses.size() == 1);  // No implicit retry.
  io.completion = 0x20;
  assert(radio.begin(policy) == ResultCode::Ready);
  io.delay_overshoot = 1000;
  const auto late = radio.transmit(command(), 44);
  assert(late.code == ResultCode::TimingMissed && late.frames_submitted < 10);
  io.delay_overshoot = 0;
  io.completion = 0xff;
  assert(radio.begin(policy) == ResultCode::Ready);
  const auto disconnected = radio.transmit(command(), 45);
  assert(disconnected.code == ResultCode::RegisterMismatch && disconnected.frames_submitted == 1 &&
         !radio.ready() && !io.ce);
}

int main() {
  payload_contract();
  gates_and_configuration();
  bounded_transmission();
  std::cout << "radio payload, configuration, gate, timing and timeout checks passed\n";
}
