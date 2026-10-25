// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include "discovery.h"

#include <array>
#include <cassert>
#include <cstdint>
#include <string>
#include <vector>

namespace {
std::vector<uint8_t> question(const std::string& name, uint16_t kind = 0x20, uint8_t suffix = 0) {
  std::array<uint8_t, 16> raw{};
  if (name == "*") {
    raw[0] = '*';
  } else {
    raw.fill(' ');
    for (size_t i = 0; i < name.size() && i < 15; ++i)
      raw[i] = name[i];
    raw[15] = suffix;
  }
  std::vector<uint8_t> result{0x12, 0x34, 0x01, 0x10, 0, 1, 0, 0, 0, 0, 0, 0, 32};
  for (auto byte : raw) {
    result.push_back('A' + (byte >> 4));
    result.push_back('A' + (byte & 15));
  }
  result.insert(result.end(),
                {0, static_cast<uint8_t>(kind >> 8), static_cast<uint8_t>(kind), 0, 1});
  return result;
}

const std::array<uint8_t, 4> ip{{192, 168, 7, 42}};
std::vector<uint8_t> reply(const std::vector<uint8_t>& request) {
  return platinum::discoveryResponse(request.data(), request.size(), ip);
}
}  // namespace

int main() {
  auto q = question("PLATLINK-PDBU");
  const auto answer = reply(q);
  assert(answer.size() == 62);
  assert(answer[0] == 0x12 && answer[1] == 0x34);
  assert(answer[2] == 0x85 && answer[3] == 0x80);
  assert(answer[7] == 1 && answer[53] == 30 && answer[55] == 6);
  assert(std::vector<uint8_t>(answer.end() - 4, answer.end()) ==
         std::vector<uint8_t>({192, 168, 7, 42}));
  assert(reply(question("platlink-pdbu")).size() == 62);
  assert(reply(question("PLATLINK-FDBU", 0x20, 0x20)).size() == 62);
  assert(reply(question("PLATLINK-PDBU", 0x20, 0x01)).empty());
  assert(reply(question("UNRELATED")).empty());
  assert(reply(question("*")).empty());
  const auto status = reply(question("*", 0x21));
  assert(status.size() == 139 && status[55] == 83 && status[56] == 2);
  assert(std::string(status.begin() + 57, status.begin() + 70) == "PLATLINK-PDBU");
  assert(std::string(status.begin() + 75, status.begin() + 88) == "PLATLINK-FDBU");
  assert(reply(question("PLATLINK-PDBU", 0x21)).size() == 139);
  assert(reply(question("PLATLINK-PDBU", 0x01)).empty());
  for (size_t size = 0; size < q.size(); ++size) {
    assert(platinum::discoveryResponse(q.data(), size, ip).empty());
  }
  q.push_back(0);
  assert(reply(q).empty());
  q.pop_back();
  for (size_t index : {size_t(2), size_t(4), size_t(6), size_t(8), size_t(10), size_t(12),
                       size_t(13), size_t(45), size_t(48)}) {
    auto malformed = q;
    malformed[index] = 0xff;
    assert(reply(malformed).empty());
  }
  assert(platinum::discoveryResponse(nullptr, 50, ip).empty());
  assert(platinum::discoveryResponse(q.data(), q.size(), {{0, 0, 0, 0}}).empty());
  assert(platinum::discoveryResponse(q.data(), q.size(), {{224, 0, 0, 1}}).empty());
  // Responses must not be reflected; recursive name registration is unsupported.
  q[2] = 0x80;
  assert(reply(q).empty());
  q[2] = 0x28;
  assert(reply(q).empty());
}
