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

enum class Operation : uint8_t { Position, Sync, Jog };
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
};

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
  Timeout
};

const char* resultName(ResultCode code);

struct Result {
  ResultCode code = ResultCode::NotReady;
  uint8_t frames_submitted = 0;
  uint8_t missing_acks = 0;
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

 private:
  SPIClass spi_;
};
#endif

}  // namespace radio
}  // namespace platinum
