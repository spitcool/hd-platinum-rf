// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>

#ifdef ARDUINO
#include <SPI.h>
#endif

namespace platinum {
namespace radio {

enum class Operation : uint8_t { Position, Sync, Jog, SecondaryPosition };
enum class Route : uint8_t { BridgeRepeater, Native };
// Bench is explicit permission to measure an unqualified module/profile. It is
// not evidence of framing, shade acceptance, or physical position.
enum class NativeAccess : uint8_t { Disabled, Bench, Qualified };
enum class Recipe : uint8_t {
  // Preserve ESB by requesting an ACK, but allow zero hardware retransmissions.
  // Missing ACKs are expected in the reference broadcast use case.
  EsbNoRetry,
  // Original gateway register evidence. EN_AA=0 plus ARC=0 can select legacy
  // ShockBurst framing; this is a separate waveform experiment, not a fallback.
  OriginalRegisterExperiment
};

struct Command {
  std::array<uint8_t, 2> room_id{};
  uint8_t mask = 0;
  Operation operation = Operation::Position;
  uint8_t position = 0;
  bool operation_enabled = false;
};

struct Policy {
  bool enabled = false;
  bool qualified = false;
  uint8_t power = 0;  // RF2401F20 module level, never a bare-chip dBm claim.
  Recipe recipe = Recipe::EsbNoRetry;
  Route route = Route::BridgeRepeater;
  NativeAccess native_position = NativeAccess::Disabled;
  NativeAccess native_jog = NativeAccess::Disabled;
  NativeAccess native_secondary = NativeAccess::Disabled;
};

// No guessed initial channel or phase counts. The diagnostic model assumes an
// idle phase-2 start, no prelude, and a nominal 200.5 us grid. These are explicit
// software inputs, not a measurement of an original bridge's complete train.
// RF-only diagnostic prefixes; neither is a qualified bridge wake procedure.
enum class NativePreparation : uint8_t { None, Wake, CommandControl };
struct NativeSchedule {
  uint8_t prior_channel = 0;
  uint8_t prior_alternate = 0;
  uint32_t command_frames = 0;
  uint32_t followup_frames = 0;
  uint16_t slot_half_us = 0;
  NativePreparation preparation = NativePreparation::None;
  uint32_t preparation_frames = 0;
};
constexpr uint16_t kNativeSlotHalfUs = 401;
constexpr uint32_t kNativeMaxDurationHalfUs = 4000000;
constexpr uint32_t kNativeSpiHz = 8000000;
constexpr uint32_t kNativeLateLimitUs = 5;
constexpr uint32_t kNativeFrameTimeoutUs = 190;

enum class NativePhase : uint8_t { Command, Followup, Wake, CommandControl };
struct NativeEvent {
  std::array<uint8_t, 5> payload{};
  uint32_t ordinal = 0;
  uint32_t start_half_us = 0;
  uint8_t channel = 0;
  NativePhase phase = NativePhase::Command;
};

// Constant-memory, side-effect-free event iterator; Sync has no native plan.
class NativePlan {
 public:
  bool begin(const Command& command, const NativeSchedule& schedule);
  bool next(NativeEvent& event);
  uint32_t frameCount() const { return count_; }
  uint32_t durationHalfUs() const { return count_ * kNativeSlotHalfUs; }

 private:
  Command command_{};
  NativeSchedule schedule_{};
  uint32_t count_ = 0, ordinal_ = 0;
  uint8_t channel_index_ = 0, alternate_ = 0, refresh_remaining_ = 0;
};
NativeAccess nativeAccess(const Policy& policy, Operation operation);

struct Payload {
  std::array<uint8_t, 12> bytes{};
  uint8_t size = 0;
};

bool encodeCommand(const Command& command, Payload& output);
bool encodeSequence(uint16_t ordinal, uint8_t countdown, Payload& output);

// Times relative to command start in eighths of a microsecond, retaining the
// reference's fractional timestamps. They are preamble targets, not CE times.
constexpr std::array<uint32_t, 10> kPreambleEighthUs = {80432,  172772, 253032, 332798, 412970,
                                                        492824, 573072, 652828, 733080, 812840};
constexpr uint32_t kBurstDurationUs = 112134;

enum class ResultCode : uint8_t {
  Ready,
  Submitted,
  Disabled,
  Unqualified,
  OperationDisabled,
  InvalidCommand,
  InvalidPolicy,
  NotReady,
  RegisterMismatch,
  Busy,
  TimingMissed,
  Timeout,
  BenchSubmitted,
  Cancelled,
  UnsupportedOperation
};

const char* resultName(ResultCode code);

struct Result {
  ResultCode code = ResultCode::NotReady;
  uint32_t frames_submitted = 0;
  uint32_t missing_acks = 0;
  uint32_t max_lateness_us = 0;
};

// All methods are called by one radio-owner task, never from an IRQ. This narrow
// boundary allows the exact register writes and failure paths to be host-tested.
class Io {
 public:
  virtual ~Io() = default;
  virtual bool begin() = 0;
  virtual void end() = 0;
  virtual void chipEnable(bool high) = 0;
  virtual uint8_t transfer(uint8_t instruction, const uint8_t* tx, uint8_t* rx, size_t size) = 0;
  virtual uint32_t micros() = 0;
  virtual void delayUs(uint32_t duration) = 0;
  // Own one fast SPI transaction throughout the finite native train. A port
  // without this capability fails closed; slow startup/register tests stay at
  // 1 MHz. This does not grant RF permission or imply electrical qualification.
  virtual bool beginTimedBurst(uint32_t) { return false; }
  virtual void endTimedBurst() {}
};

class Radio {
 public:
  explicit Radio(Io& io) : io_(io) {}
  // External owner must first establish the carrier rail; this never enables
  // M-Bus power. Startup only programs the radio; CE remains low.
  ResultCode begin(const Policy& policy);
  // Reserve ordinal durably BEFORE calling this. Never retry/reuse it after
  // interruption or failure. A Submitted result is not proof of shade motion.
  Result transmit(const Command& command, uint16_t ordinal);
  // Native packets contain no bridge transaction ordinal. Cancellation is
  // checked before every CE and during waits; callbacks must be bounded and
  // must not perform radio I/O. A started packet may finish after cancellation.
  Result transmitNative(const Command& command, const NativeSchedule& schedule,
                        bool (*cancel)(void*) = nullptr, void* context = nullptr);
  // Call before removing the carrier supply; returns GPIOs to high impedance.
  // Owner must serialize this with transmit (there are no concurrent callers).
  void shutdown();
  bool ready() const {
    return ready_;
  }

 private:
  uint8_t read(uint8_t reg);
  void write(uint8_t reg, uint8_t value);
  bool verify(uint8_t reg, uint8_t value);
  void clearAndFlush();
  bool nativeRegistersMatch();
  Io& io_;
  Policy policy_{};
  bool initialized_ = false;
  bool ready_ = false;
  bool active_ = false;
};

#ifdef ARDUINO
class ArduinoIo final : public Io {
 public:
  static constexpr int kSck = 6;
  static constexpr int kMosi = 5;
  static constexpr int kMiso = 8;
  static constexpr int kCsn = 18;
  static constexpr int kCe = 17;
  static constexpr int kIrq = 10;
  ArduinoIo();
  bool begin() override;
  void end() override;
  void chipEnable(bool high) override;
  uint8_t transfer(uint8_t instruction, const uint8_t* tx, uint8_t* rx, size_t size) override;
  uint32_t micros() override;
  void delayUs(uint32_t duration) override;
  bool beginTimedBurst(uint32_t spi_hz) override;
  void endTimedBurst() override;

 private:
  SPIClass spi_;
  bool timed_burst_ = false;
};
#endif

}  // namespace radio
}  // namespace platinum
