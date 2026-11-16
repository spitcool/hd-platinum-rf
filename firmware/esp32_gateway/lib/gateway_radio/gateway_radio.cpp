// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include "gateway_radio.h"

#include <algorithm>

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
    case ResultCode::BenchSubmitted:
      return "bench_submitted_unqualified";
    case ResultCode::Cancelled:
      return "radio_cancelled";
    case ResultCode::UnsupportedOperation:
      return "unsupported_radio_operation";
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
  const auto validAccess = [](NativeAccess access) {
    return access == NativeAccess::Disabled || access == NativeAccess::Bench ||
           access == NativeAccess::Qualified;
  };
  if (policy.power > 2 ||
      (policy.recipe != Recipe::EsbNoRetry && policy.recipe != Recipe::OriginalRegisterExperiment) ||
      (policy.route != Route::BridgeRepeater && policy.route != Route::Native) ||
      !validAccess(policy.native_position) || !validAccess(policy.native_jog) ||
      !validAccess(policy.native_secondary))
    return ResultCode::InvalidPolicy;
  policy_ = policy;
  if (!io_.begin())
    return ResultCode::NotReady;
  initialized_ = true;
  io_.chipEnable(false);
  // Power-down while changing framing and addresses. No library defaults and
  // no ACTIVATE toggle: a feature-register mismatch fails closed.
  bool valid = verify(kConfig, 0x0c);
  const bool native = policy.route == Route::Native;
  valid &= verify(kAutoAck, !native && policy.recipe == Recipe::EsbNoRetry ? 1 : 0);
  valid &= verify(kRxEnable, 1);
  valid &= verify(kAddressWidth, 1);  // Three-byte address.
  valid &= verify(kRetry, 0);         // ARC=0: zero hardware retransmissions.
  valid &= verify(kChannel, native ? 33 : 40);
  valid &= verify(kRfSetup, (native ? 0x08 : 0x20) | (policy.power << 1));
  valid &= verify(kRxWidth, native ? 5 : 0);
  valid &= verify(kDynamicPayload, native ? 0 : 1);
  valid &= verify(kFeature, native ? 0 : 4);
  // Native is a register experiment: Nordic PS v1.0 section 7.9 guarantees
  // legacy no-PCF interoperability only at 1 Mbps/250 kbps. EN_AA=ARC=DPL=0
  // at 2 Mbps must be captured on this exact module before qualification.
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
  if (policy_.route != Route::BridgeRepeater) {
    result.code = ResultCode::InvalidPolicy;
    return result;
  }
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

bool Radio::nativeRegistersMatch() {
  // Recheck at the fast SPI clock, before CE. No ACTIVATE toggles or fallback
  // to another framing recipe on a mismatch.
  bool valid = read(kConfig) == 0x0e && read(kAutoAck) == 0 && read(kRxEnable) == 1 &&
      read(kAddressWidth) == 1 && read(kRetry) == 0 &&
      read(kRfSetup) == (0x08 | (policy_.power << 1)) && read(kRxWidth) == 5 &&
      read(kDynamicPayload) == 0 && read(kFeature) == 0;
  for (uint8_t reg : {kRxAddress, kTxAddress}) {
    uint8_t received[3]{};
    io_.transfer(reg, nullptr, received, 3);
    valid &= received[0] == 0xe7 && received[1] == 0xe7 && received[2] == 0xe7;
  }
  return valid && (read(kFifoStatus) & 0x11) == 0x11;
}

Result Radio::transmitNative(const Command& command, const NativeSchedule& schedule,
                             bool (*cancel)(void*), void* context) {
  Result result;
  if (active_) {
    result.code = ResultCode::Busy;
    return result;
  }
  if (policy_.route != Route::Native) {
    result.code = ResultCode::InvalidPolicy;
    return result;
  }
  if (!policy_.enabled) {
    result.code = ResultCode::Disabled;
    return result;
  }
  if (command.operation == Operation::Sync) {
    result.code = ResultCode::UnsupportedOperation;
    return result;
  }
  NativePlan plan;
  if (!plan.begin(command, schedule)) {
    result.code = ResultCode::InvalidCommand;
    return result;
  }
  if (!command.operation_enabled) {
    result.code = ResultCode::OperationDisabled;
    return result;
  }
  const NativeAccess access = nativeAccess(policy_, command.operation);
  if (access == NativeAccess::Disabled ||
      (schedule.preparation != NativePreparation::None && access != NativeAccess::Bench)) {
    result.code = ResultCode::Unqualified;
    return result;
  }
  if (!ready_)
    return result;
  if (!io_.beginTimedBurst(kNativeSpiHz)) {
    write(kConfig, 0x0c);
    ready_ = false;
    return result;
  }
  active_ = true;
  bool cancellation_requested = false;
  const auto cancelled = [&]() {
    if (cancel && !cancellation_requested)
      cancellation_requested = cancel(context);
    return cancellation_requested;
  };
  result.code = access == NativeAccess::Bench ? ResultCode::BenchSubmitted : ResultCode::Submitted;
  clearAndFlush();
  if (!nativeRegistersMatch())
    result.code = ResultCode::RegisterMismatch;
  // A short preparation allowance precedes the first CE. Subsequent targets
  // use ceil(ordinal * 401 / 2), NOT repeated 201 us delays. Quantization is
  // at most 0.5 us and does not accumulate. Targets are CE edges, not measured
  // RF preambles; the module supplies its own PLL settling and pulse envelope.
  constexpr uint32_t firstCeUs = 32;
  const uint32_t start = io_.micros();
  NativeEvent event;
  const auto submitted = [&]() {
    return result.code == ResultCode::Submitted || result.code == ResultCode::BenchSubmitted;
  };
  while (submitted() && plan.next(event)) {
    if (cancelled()) {
      result.code = ResultCode::Cancelled;
      break;
    }
    if (!verify(kChannel, event.channel)) {
      result.code = ResultCode::RegisterMismatch;
      break;
    }
    const uint8_t loaded = io_.transfer(kTxPayload, event.payload.data(), nullptr, event.payload.size());
    if (loaded & (0x80 | kMaxRetry | kTxDone | 1)) {
      result.code = ResultCode::RegisterMismatch;
      break;
    }
    const uint32_t target = firstCeUs + (event.start_half_us + 1) / 2;
    uint32_t elapsed = io_.micros() - start;
    while (elapsed < target && !cancelled()) {
      io_.delayUs(std::min(uint32_t{10}, target - elapsed));
      elapsed = io_.micros() - start;
    }
    if (cancelled()) {
      result.code = ResultCode::Cancelled;
      break;
    }
    elapsed = io_.micros() - start;
    const uint32_t late = elapsed > target ? elapsed - target : 0;
    result.max_lateness_us = std::max(result.max_lateness_us, late);
    if (late > kNativeLateLimitUs) {
      result.code = ResultCode::TimingMissed;
      break;
    }
    const uint32_t pulse = io_.micros();
    io_.chipEnable(true);
    io_.delayUs(10);
    io_.chipEnable(false);
    ++result.frames_submitted;
    bool cancellation_seen = false;
    // Nordic PS v1.0 table 16: 130 us standby->TX, CE >=10 us. The expected
    // 88-bit packet takes 44 us; even a 97-bit ESB packet is <49 us. Allow 190 us
    // total, including TX_DS propagation, then fail rather than changing rate.
    while (io_.micros() - pulse < 170) {
      cancellation_seen |= cancelled();
      const uint32_t age = io_.micros() - pulse;
      if (age < 170)
        io_.delayUs(std::min(uint32_t{10}, 170 - age));
    }
    uint8_t status = 0;
    do {
      cancellation_seen |= cancelled();
      status = io_.transfer(kNop, nullptr, nullptr, 0);
      if (status & (0x80 | kMaxRetry | kTxDone))
        break;
      if (io_.micros() - pulse >= kNativeFrameTimeoutUs)
        break;
      io_.delayUs(1);
    } while (io_.micros() - pulse < kNativeFrameTimeoutUs);
    if (io_.micros() - pulse > kNativeFrameTimeoutUs)
      result.code = ResultCode::Timeout;
    else if (status & (0x80 | kMaxRetry))
      result.code = ResultCode::RegisterMismatch;
    else if (!(status & kTxDone))
      result.code = ResultCode::Timeout;
    else if (!(read(kFifoStatus) & 0x10))
      result.code = ResultCode::RegisterMismatch;
    else if (cancellation_seen || cancelled())
      result.code = ResultCode::Cancelled;
    if (!submitted()) {
      // No new CE after cancellation/failure. Allow the already-started packet
      // its bounded completion interval before flushing/powering down.
      const uint32_t age = io_.micros() - pulse;
      if (age < kNativeFrameTimeoutUs)
        io_.delayUs(kNativeFrameTimeoutUs - age);
      break;
    }
    write(kStatus, 0x70);
  }
  if (submitted()) {
    const uint32_t end = firstCeUs + (plan.durationHalfUs() + 1) / 2;
    while (io_.micros() - start < end) {
      if (cancelled()) {
        result.code = ResultCode::Cancelled;
        break;
      }
      io_.delayUs(1);
    }
  }
  clearAndFlush();
  if (!submitted()) {
    write(kConfig, 0x0c);
    ready_ = false;
  }
  io_.endTimedBurst();
  active_ = false;
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
  endTimedBurst();
  spi_.end();
  for (int pin : {kCsn, kCe, kSck, kMosi, kMiso, kIrq})
    pinMode(pin, INPUT);
}
void ArduinoIo::chipEnable(bool high) {
  digitalWrite(kCe, high ? HIGH : LOW);
}
uint8_t ArduinoIo::transfer(uint8_t instruction, const uint8_t* tx, uint8_t* rx, size_t size) {
  if (timed_burst_) {
    if (size > 32)
      return 0xff;
    uint8_t outgoing[33], incoming[33];
    outgoing[0] = instruction;
    for (size_t i = 0; i < size; ++i)
      outgoing[i + 1] = tx ? tx[i] : 0xff;
    digitalWrite(kCsn, LOW);
    // One hardware transaction avoids per-byte Arduino call overhead in the
    // small interval between TX_DS and the following channel/CE deadline.
    spi_.transferBytes(outgoing, incoming, size + 1);
    digitalWrite(kCsn, HIGH);
    if (rx)
      std::copy(incoming + 1, incoming + size + 1, rx);
    return incoming[0];
  }
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
bool ArduinoIo::beginTimedBurst(uint32_t spi_hz) {
  if (timed_burst_ || spi_hz != kNativeSpiHz)
    return false;
  // Nordic nRF24L01+ PS v1.0 sections 8.1/8.2 allow up to 10 MHz SPI. Use 8 MHz
  // (also within the earlier nRF24L01 limit); actual carrier integrity remains
  // a bench qualification requirement. Initialization/readback begins at 1 MHz.
  spi_.beginTransaction(SPISettings(spi_hz, MSBFIRST, SPI_MODE0));
  timed_burst_ = true;
  return true;
}
void ArduinoIo::endTimedBurst() {
  if (timed_burst_) {
    spi_.endTransaction();
    timed_burst_ = false;
  }
}
#endif

}  // namespace radio
}  // namespace platinum
