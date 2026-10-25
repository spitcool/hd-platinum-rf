// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <algorithm>
#include <cstddef>
#include <cstdint>
#include <string>
#include <utility>
namespace platinum {
namespace http {
enum class PumpResult { Pending, Complete, Fault };
// One bounded response, drained by the network owner. Socket availability and
// deadlines belong to that owner; zero progress never spins inside this helper.
class OutputBuffer {
 public:
  static constexpr size_t DefaultLimit = 131072;
  static constexpr size_t ChunkSize = 512;
  explicit OutputBuffer(size_t limit = DefaultLimit) : limit_(limit) {}
  bool assign(std::string bytes) {
    clear();
    if (bytes.size() > limit_)
      return false;
    bytes_ = std::move(bytes);
    return true;
  }
  void clear() {
    bytes_.clear();
    offset_ = 0;
  }
  bool pending() const {
    return offset_ < bytes_.size();
  }
  size_t remaining() const {
    return bytes_.size() - offset_;
  }
  size_t size() const {
    return bytes_.size();
  }
  template <typename Write>
  PumpResult pump(Write&& write) {
    if (!pending())
      return PumpResult::Complete;
    const size_t offered = std::min(ChunkSize, remaining());
    const size_t written =
        write(reinterpret_cast<const uint8_t*>(bytes_.data() + offset_), offered);
    if (written > offered) {
      clear();
      return PumpResult::Fault;
    }
    offset_ += written;
    if (!pending()) {
      clear();
      return PumpResult::Complete;
    }
    return PumpResult::Pending;
  }

 private:
  std::string bytes_;
  size_t offset_ = 0;
  size_t limit_;
};
}  // namespace http
}  // namespace platinum
