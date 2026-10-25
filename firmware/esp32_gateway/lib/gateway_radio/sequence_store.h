// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

#include <cstdint>
#include <functional>
#include <optional>
#include <utility>

namespace platinum {
namespace radio {

enum class SequenceRead : uint8_t { Present, Absent, Corrupt, Failure };
enum class SequenceStatus : uint8_t { Ready, Absent, Corrupt, Exhausted, StorageFault };

struct SequenceHooks {
  std::function<SequenceRead(uint32_t&)> read;
  // Success must mean durably committed, not merely buffered. A failed write
  // may still have committed; callers must never infer that its ordinal is free.
  std::function<bool(uint32_t)> write;
};

// Single-owner allocator. Store next ordinal independently of importable gateway
// configuration and never erase it during normal upgrades/configuration reset.
// Physical NVS atomicity/CRC and power interruption tests remain platform duties.
class SequenceStore {
 public:
  explicit SequenceStore(SequenceHooks hooks) : hooks_(std::move(hooks)) {}
  SequenceStatus status() const {
    return status_;
  }

  std::optional<uint16_t> allocate() {
    if (faulted_)
      return std::nullopt;
    uint32_t next = 0;
    if (!read(next))
      return std::nullopt;
    if (next == 65536) {
      fail(SequenceStatus::Exhausted);
      return std::nullopt;
    }
    if (!commit(next + 1))
      return std::nullopt;
    return static_cast<uint16_t>(next);
  }

  // Explicit one-time provisioning only. It cannot reset an existing store,
  // recover an ambiguous write, or reuse ordinals after a fault in this instance.
  bool initialize(uint16_t first_unused) {
    if (faulted_ || !hooks_.read || !hooks_.write) {
      if (!faulted_)
        fail(SequenceStatus::StorageFault);
      return false;
    }
    uint32_t existing = 0;
    const auto state = hooks_.read(existing);
    if (state != SequenceRead::Absent || watermark_.has_value()) {
      if (state == SequenceRead::Failure)
        fail(SequenceStatus::StorageFault);
      else if (state == SequenceRead::Corrupt || existing > 65536 ||
               (watermark_ && state == SequenceRead::Absent))
        fail(SequenceStatus::Corrupt);
      else
        status_ = existing == 65536 ? SequenceStatus::Exhausted : SequenceStatus::Ready;
      return false;
    }
    return commit(first_unused);
  }

 private:
  void fail(SequenceStatus status) {
    status_ = status;
    faulted_ = true;
  }

  bool read(uint32_t& value) {
    if (!hooks_.read || !hooks_.write) {
      fail(SequenceStatus::StorageFault);
      return false;
    }
    switch (hooks_.read(value)) {
      case SequenceRead::Failure:
        fail(SequenceStatus::StorageFault);
        return false;
      case SequenceRead::Corrupt:
        fail(SequenceStatus::Corrupt);
        return false;
      case SequenceRead::Absent:
        if (watermark_)
          fail(SequenceStatus::Corrupt);
        else
          status_ = SequenceStatus::Absent;
        return false;
      case SequenceRead::Present:
        break;
    }
    if (value > 65536 || (watermark_ && value < *watermark_)) {
      fail(SequenceStatus::Corrupt);
      return false;
    }
    watermark_ = value;
    status_ = SequenceStatus::Ready;
    return true;
  }

  bool commit(uint32_t value) {
    if (!hooks_.write(value)) {
      fail(SequenceStatus::StorageFault);
      return false;
    }
    uint32_t verified = 0;
    if (hooks_.read(verified) != SequenceRead::Present || verified != value) {
      fail(SequenceStatus::StorageFault);
      return false;
    }
    watermark_ = value;
    status_ = SequenceStatus::Ready;
    return true;
  }

  SequenceHooks hooks_;
  SequenceStatus status_ = SequenceStatus::Absent;
  std::optional<uint32_t> watermark_;
  bool faulted_ = false;
};

}  // namespace radio
}  // namespace platinum
