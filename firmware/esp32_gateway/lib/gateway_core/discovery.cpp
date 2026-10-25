// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include "discovery.h"

#include <algorithm>
#include <cstring>

namespace platinum {
namespace {
constexpr const char* kNames[] = {"PLATLINK-PDBU", "PLATLINK-FDBU"};

uint16_t word(const uint8_t* p) {
  return static_cast<uint16_t>((static_cast<uint16_t>(p[0]) << 8) | p[1]);
}

void appendWord(std::vector<uint8_t>& out, uint16_t value) {
  out.push_back(static_cast<uint8_t>(value >> 8));
  out.push_back(static_cast<uint8_t>(value));
}

void appendDword(std::vector<uint8_t>& out, uint32_t value) {
  appendWord(out, static_cast<uint16_t>(value >> 16));
  appendWord(out, static_cast<uint16_t>(value));
}

bool validAddress(const std::array<uint8_t, 4>& ip) {
  // A station must have acquired an address before advertising. The network
  // adapter applies the actual interface subnet policy (including routed LANs).
  return ip[0] != 0 && ip[0] < 224 && ip != std::array<uint8_t, 4>{{255, 255, 255, 255}};
}

bool knownName(const std::array<uint8_t, 16>& raw) {
  if (raw[15] != 0 && raw[15] != 0x20)
    return false;
  for (const char* name : kNames) {
    bool matches = true;
    const size_t length = std::strlen(name);
    for (size_t i = 0; i < 15; ++i) {
      uint8_t value = raw[i];
      if (value >= 'a' && value <= 'z')
        value -= 'a' - 'A';
      const uint8_t expected = i < length ? static_cast<uint8_t>(name[i]) : ' ';
      if (value != expected)
        matches = false;
    }
    if (matches)
      return true;
  }
  return false;
}
}  // namespace

std::vector<uint8_t> discoveryResponse(const uint8_t* data, size_t size,
                                       const std::array<uint8_t, 4>& ip) {
  // RFC 1002 uncompressed, unscoped, single-question NB/NBSTAT requests.
  // A complete question is 12 header + 34 encoded name + 4 type/class bytes.
  if (data == nullptr || size != 50 || !validAddress(ip))
    return {};
  const uint16_t flags = word(data + 2);
  if ((flags & 0xf800) != 0 || word(data + 4) != 1 || word(data + 6) != 0 || word(data + 8) != 0 ||
      word(data + 10) != 0 || data[12] != 32 || data[45] != 0) {
    return {};
  }
  const uint16_t kind = word(data + 46);
  if (word(data + 48) != 1 || (kind != 0x20 && kind != 0x21))
    return {};
  std::array<uint8_t, 16> raw{};
  for (size_t i = 0; i < raw.size(); ++i) {
    const uint8_t high = data[13 + 2 * i], low = data[14 + 2 * i];
    if (high < 'A' || high > 'P' || low < 'A' || low > 'P')
      return {};
    raw[i] = static_cast<uint8_t>(((high - 'A') << 4) | (low - 'A'));
  }
  const bool wildcard = raw[0] == '*' && std::all_of(raw.begin() + 1, raw.end(),
                                                     [](uint8_t byte) { return byte == 0; });
  if (!knownName(raw) && !(kind == 0x21 && wildcard))
    return {};

  std::vector<uint8_t> out;
  out.reserve(139);
  appendWord(out, word(data));
  appendWord(out, kind == 0x20 ? static_cast<uint16_t>(0x8480 | (flags & 0x0100)) : 0x8400);
  appendWord(out, 0);  // No echoed question; answer carries the name.
  appendWord(out, 1);
  appendWord(out, 0);
  appendWord(out, 0);
  out.insert(out.end(), data + 12, data + 46);
  appendWord(out, kind);
  appendWord(out, 1);
  appendDword(out, kind == 0x20 ? 30 : 0);
  if (kind == 0x20) {
    appendWord(out, 6);
    appendWord(out, 0);  // Unique B-node flags.
    out.insert(out.end(), ip.begin(), ip.end());
  } else {
    appendWord(out, 83);  // Count + two 18-byte names + 46-byte statistics.
    out.push_back(2);
    for (const char* name : kNames) {
      const size_t length = std::strlen(name);
      out.insert(out.end(), name, name + length);
      out.insert(out.end(), 15 - length, ' ');
      out.push_back(0);         // Workstation suffix.
      appendWord(out, 0x0400);  // Active unique name.
    }
    // Unspecified unit ID and statistics: never impersonate the old MAC.
    out.insert(out.end(), 46, 0);
  }
  return out;
}
}  // namespace platinum
