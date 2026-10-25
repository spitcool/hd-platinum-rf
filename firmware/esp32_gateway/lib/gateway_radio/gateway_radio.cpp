// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include "gateway_radio.h"

#ifdef ARDUINO
#include <Arduino.h>
#endif

namespace platinum {
namespace radio {
namespace {
constexpr uint8_t kConfig = 0x00;
constexpr uint8_t kAutoAck = 0x01;
constexpr uint8_t kRxEnable = 0x02;
constexpr uint8_t kAddressWidth = 0x03;
constexpr uint8_t kRetry = 0x04;
constexpr uint8_t kChannel = 0x05;
constexpr uint8_t kRfSetup = 0x06;
constexpr uint8_t kStatus = 0x07;
constexpr uint8_t kRxAddress = 0x0a;
constexpr uint8_t kTxAddress = 0x10;
constexpr uint8_t kRxWidth = 0x11;
constexpr uint8_t kFifoStatus = 0x17;
constexpr uint8_t kDynamicPayload = 0x1c;
constexpr uint8_t kFeature = 0x1d;
constexpr uint8_t kWrite = 0x20;
constexpr uint8_t kTxPayload = 0xa0;
constexpr uint8_t kFlushTx = 0xe1;
constexpr uint8_t kFlushRx = 0xe2;
constexpr uint8_t kNop = 0xff;
constexpr uint8_t kTxDone = 0x20;
constexpr uint8_t kMaxRetry = 0x10;
constexpr uint32_t kTxSettleUs = 130;
constexpr uint32_t kFrameTimeoutUs = 3000;
constexpr uint32_t kLateLimitUs = 500;

void checksum(Payload& payload) {
  uint8_t value = 0xff;
  for (uint8_t i = 1; i + 1 < payload.size; ++i)
    value ^= payload.bytes[i];
  payload.bytes[payload.size - 1] = value;
}
}  // namespace

bool encodeCommand(const Command& command, Payload& output) {
  output = Payload{};
  if (command.mask == 0 || (command.mask & (command.mask - 1)) != 0)
    return false;
  uint8_t feature, value, flags;
  switch (command.operation) {
    case Operation::Position:
      feature = 4;
      value = command.position;
      flags = 1;
      break;
    case Operation::Sync:
      feature = 1;
      value = 0;
      flags = 3;
      break;
    case Operation::Jog:
      feature = 12;
      value = 1;
      flags = 1;
      break;
    default:
      return false;
  }
  output.bytes = {{1, 10, 2, 0x34, command.room_id[0], command.room_id[1], feature, command.mask,
                   value, 0, flags, 0}};
  output.size = 12;
  checksum(output);
  return true;
}

bool encodeSequence(uint16_t ordinal, uint8_t countdown, Payload& output) {
  output = Payload{};
  if (countdown > 4)
    return false;
  output.bytes = {{1, 7, 2, 0x38, 1, static_cast<uint8_t>(ordinal), countdown, 6, 0, 0, 0, 0}};
  output.size = 9;
  checksum(output);
  return true;
}

const char* resultName(ResultCode code) {
  switch (code) {
    case ResultCode::Ready:
      return "radio_ready";
    case ResultCode::Submitted:
      return "submitted_unconfirmed";
    case ResultCode::Disabled:
      return "rf_disabled";
    case ResultCode::Unqualified:
      return "rf_unqualified";
    case ResultCode::OperationDisabled:
      return "operation_disabled";
    case ResultCode::InvalidCommand:
      return "invalid_command";
    case ResultCode::InvalidPolicy:
      return "invalid_radio_policy";
    case ResultCode::NotReady:
      return "radio_not_ready";
    case ResultCode::RegisterMismatch:
      return "radio_register_mismatch";
    case ResultCode::Busy:
      return "radio_busy";
    case ResultCode::TimingMissed:
      return "radio_timing_missed";
    case ResultCode::Timeout:
      return "radio_timeout";
  }
  return "unknown_radio_result";
}

uint8_t Radio::read(uint8_t reg) {
  uint8_t value = 0;
  io_.transfer(reg, nullptr, &value, 1);
  return value;
}
void Radio::write(uint8_t reg, uint8_t value) {
  io_.transfer(kWrite | reg, &value, nullptr, 1);
}
bool Radio::verify(uint8_t reg, uint8_t value) {
  write(reg, value);
  return read(reg) == value;
}
void Radio::clearAndFlush() {
  io_.chipEnable(false);
  write(kStatus, 0x70);
  io_.transfer(kFlushTx, nullptr, nullptr, 0);
  io_.transfer(kFlushRx, nullptr, nullptr, 0);
}

ResultCode Radio::begin(const Policy& policy) {
  if (active_)
    return ResultCode::Busy;
  shutdown();
  if (policy.power > 2 ||
      (policy.recipe != Recipe::EsbNoRetry && policy.recipe != Recipe::OriginalRegisterExperiment))
    return ResultCode::InvalidPolicy;
  policy_ = policy;
  if (!io_.begin())
    return ResultCode::NotReady;
  initialized_ = true;
  io_.chipEnable(false);
  // Power-down while changing framing and addresses. No library defaults and
  // no ACTIVATE toggle: a feature-register mismatch fails closed.
  bool valid = verify(kConfig, 0x0c);
  valid &= verify(kAutoAck, policy.recipe == Recipe::EsbNoRetry ? 1 : 0);
  valid &= verify(kRxEnable, 1);
  valid &= verify(kAddressWidth, 1);  // Three-byte address.
  valid &= verify(kRetry, 0);         // ARC=0: zero hardware retransmissions.
  valid &= verify(kChannel, 40);
  valid &= verify(kRfSetup, 0x20 | (policy.power << 1));  // 250 kbps.
  valid &= verify(kRxWidth, 0);
  valid &= verify(kDynamicPayload, 1);
  valid &= verify(kFeature, 4);  // Dynamic payload only; not dynamic ACK.
  const uint8_t address[] = {0xe7, 0xe7, 0xe7};
  uint8_t received[3]{};
  for (uint8_t reg : {kRxAddress, kTxAddress}) {
    io_.transfer(kWrite | reg, address, nullptr, 3);
    io_.transfer(reg, nullptr, received, 3);
    for (size_t i = 0; i < 3; ++i)
      valid &= received[i] == address[i];
  }
  clearAndFlush();
  valid &= (read(kFifoStatus) & 0x11) == 0x11;
  if (!valid || !verify(kConfig, 0x0e)) {
    shutdown();
    return ResultCode::RegisterMismatch;
  }
  io_.delayUs(5000);  // Exceeds nRF24's maximum 1.5 ms power-up settling.
  ready_ = true;
  return ResultCode::Ready;  // No CE pulse has occurred.
}

Result Radio::transmit(const Command& command, uint16_t ordinal) {
  Result result;
  if (!policy_.enabled) {
    result.code = ResultCode::Disabled;
    return result;
  }
  if (!policy_.qualified) {
    result.code = ResultCode::Unqualified;
    return result;
  }
  if (!command.operation_enabled) {
    result.code = ResultCode::OperationDisabled;
    return result;
  }
  Payload long_packet;
  if (!encodeCommand(command, long_packet)) {
    result.code = ResultCode::InvalidCommand;
    return result;
  }
  if (!ready_)
    return result;
  if (active_) {
    result.code = ResultCode::Busy;
    return result;
  }
  active_ = true;
  clearAndFlush();
  const uint32_t start = io_.micros();
  result.code = ResultCode::Submitted;
  for (uint8_t frame = 0; frame < 10; ++frame) {
    Payload payload = long_packet;
    if (frame & 1)
      encodeSequence(ordinal, 4 - frame / 2, payload);
    io_.transfer(kTxPayload, payload.bytes.data(), nullptr, payload.size);
    // CE-to-preamble is nominal only. Native radio lacks the SDR's explicit
    // 54 us carrier lead; actual timing and PID generation require an RF trace.
    const uint32_t target = (kPreambleEighthUs[frame] + 7) / 8 - kTxSettleUs;
    uint32_t elapsed = io_.micros() - start;
    if (elapsed > target + kLateLimitUs) {
      result.code = ResultCode::TimingMissed;
      break;
    }
    if (elapsed < target)
      io_.delayUs(target - elapsed);
    if (io_.micros() - start > target + kLateLimitUs) {
      result.code = ResultCode::TimingMissed;
      break;
    }
    io_.chipEnable(true);
    io_.delayUs(15);  // Greater than the 10 us minimum CE pulse.
    io_.chipEnable(false);
    ++result.frames_submitted;
    const uint32_t submitted = io_.micros();
    uint8_t status;
    do {
      status = io_.transfer(kNop, nullptr, nullptr, 0);
      if (status & 0x80)
        break;  // Reserved bit; disconnected MISO often reads ff.
      if (status & (kTxDone | kMaxRetry))
        break;
      io_.delayUs(20);
    } while (io_.micros() - submitted < kFrameTimeoutUs);
    if (status & 0x80) {
      result.code = ResultCode::RegisterMismatch;
      break;
    }
    if (!(status & (kTxDone | kMaxRetry))) {
      result.code = ResultCode::Timeout;
      break;
    }
    if (status & kMaxRetry)
      ++result.missing_acks;
    // MAX_RT keeps payload in FIFO. Discard it deliberately, never REUSE_TX_PL.
    write(kStatus, 0x70);
    io_.transfer(kFlushTx, nullptr, nullptr, 0);
  }
  clearAndFlush();
  if (result.code == ResultCode::Submitted) {
    const uint32_t elapsed = io_.micros() - start;
    if (elapsed < kBurstDurationUs)
      io_.delayUs(kBurstDurationUs - elapsed);
  }
  active_ = false;
  if (result.code != ResultCode::Submitted) {
    // An interrupted or mistimed burst requires explicit reinitialization.
    write(kConfig, 0x0c);
    ready_ = false;
  }
  return result;
}

void Radio::shutdown() {
  if (!initialized_) {
    ready_ = false;
    return;
  }
  clearAndFlush();
  write(kConfig, 0x0c);
  io_.end();
  initialized_ = false;
  ready_ = false;
}

#ifdef ARDUINO
ArduinoIo::ArduinoIo() : spi_(HSPI) {}
bool ArduinoIo::begin() {
  digitalWrite(kCe, LOW);
  pinMode(kCe, OUTPUT);
  digitalWrite(kCsn, HIGH);
  pinMode(kCsn, OUTPUT);
  digitalWrite(kSck, LOW);
  pinMode(kSck, OUTPUT);
  pinMode(kIrq, INPUT);
  spi_.begin(kSck, kMiso, kMosi, kCsn);
  return true;  // Register readback in Radio::begin verifies the entire path.
}
void ArduinoIo::end() {
  digitalWrite(kCe, LOW);
  spi_.end();
  for (int pin : {kCsn, kCe, kSck, kMosi, kMiso, kIrq})
    pinMode(pin, INPUT);
}
void ArduinoIo::chipEnable(bool high) {
  digitalWrite(kCe, high ? HIGH : LOW);
}
uint8_t ArduinoIo::transfer(uint8_t instruction, const uint8_t* tx, uint8_t* rx, size_t size) {
  spi_.beginTransaction(SPISettings(1000000, MSBFIRST, SPI_MODE0));
  digitalWrite(kCsn, LOW);
  const uint8_t status = spi_.transfer(instruction);
  for (size_t i = 0; i < size; ++i) {
    const uint8_t value = spi_.transfer(tx ? tx[i] : 0xff);
    if (rx)
      rx[i] = value;
  }
  digitalWrite(kCsn, HIGH);
  spi_.endTransaction();
  return status;
}
uint32_t ArduinoIo::micros() {
  return ::micros();
}
void ArduinoIo::delayUs(uint32_t duration) {
  delayMicroseconds(duration);
}
#endif

}  // namespace radio
}  // namespace platinum
