// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include <algorithm>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>

#include "output_buffer.h"
using namespace platinum::http;
namespace {
std::string response() {
  std::string body = "<!doctype html><html>";
  for (size_t i = 0; i < 25 * 1024; ++i)
    body.push_back(char('a' + i % 26));
  body += "</html>";
  return "HTTP/1.1 200 OK\r\nContent-Type: text/html\r\nContent-Length: " +
         std::to_string(body.size()) + "\r\nConnection: close\r\n\r\n" + body;
}
void ethernetRegression() {
  const auto expected = response();
  OutputBuffer buffer;
  assert(buffer.assign(expected));
  assert(buffer.pending() && buffer.size() == expected.size());
  std::string received;
  size_t largestOffer = 0, calls = 0;
  // Models Ethernet 2.0.2: socketSend clips at 2048, but Client::write returns
  // the requested count. A one-call body write would therefore silently lose data.
  auto ethernet = [&](const uint8_t* bytes, size_t count) {
    ++calls;
    largestOffer = std::max(largestOffer, count);
    received.append(reinterpret_cast<const char*>(bytes), std::min(count, size_t(2048)));
    return count;
  };
  while (buffer.pending()) {
    auto result = buffer.pump(ethernet);
    assert(result != PumpResult::Fault);
    assert((result == PumpResult::Pending) == buffer.pending());
  }
  assert(received == expected);
  assert(largestOffer == 512 && calls > 50);
  assert(buffer.remaining() == 0 && buffer.size() == 0);
  assert(buffer.pump(ethernet) == PumpResult::Complete);
  assert(calls > 50);
}
void shortWrites() {
  const auto expected = response();
  OutputBuffer buffer;
  assert(buffer.assign(expected));
  std::string received;
  size_t calls = 0;
  while (buffer.pending()) {
    size_t before = buffer.remaining(), actual = 0;
    auto result = buffer.pump([&](const uint8_t* data, size_t count) {
      ++calls;
      assert(count <= 512);
      actual = calls % 3 ? std::min(count, size_t(7)) : 0;
      received.append(reinterpret_cast<const char*>(data), actual);
      return actual;
    });
    assert(result != PumpResult::Fault);
    assert(buffer.remaining() == before - actual);
    assert(calls < expected.size());
  }
  assert(received == expected);
  assert(buffer.pump([](const uint8_t*, size_t) -> size_t {
    assert(false);
    return 0;
  }) == PumpResult::Complete);
}
void boundsAndFailures() {
  OutputBuffer buffer(5);
  assert(buffer.assign("hello"));
  assert(buffer.pump([](const uint8_t*, size_t) { return size_t(0); }) == PumpResult::Pending);
  assert(buffer.remaining() == 5);
  assert(!buffer.assign("toolong"));
  assert(!buffer.pending() && buffer.size() == 0);
  assert(buffer.assign("hello"));
  assert(buffer.pump([](const uint8_t*, size_t n) { return n + 1; }) == PumpResult::Fault);
  assert(!buffer.pending());
  assert(buffer.assign("hello"));
  assert(buffer.pump([](const uint8_t*, size_t) { return std::numeric_limits<size_t>::max(); }) ==
         PumpResult::Fault);
  assert(!buffer.pending());
  assert(buffer.assign("hello"));
  buffer.pump([](const uint8_t*, size_t) { return size_t(2); });
  assert(buffer.remaining() == 3);
  assert(buffer.assign("new"));
  std::string received;
  assert(buffer.pump([&](const uint8_t* data, size_t n) {
    received.append(reinterpret_cast<const char*>(data), n);
    return n;
  }) == PumpResult::Complete);
  assert(received == "new");
  assert(buffer.assign(""));
  assert(buffer.pump([](const uint8_t*, size_t) -> size_t {
    assert(false);
    return 0;
  }) == PumpResult::Complete);
  OutputBuffer defaults;
  assert(defaults.assign(std::string(131072, 'x')));
  assert(!defaults.assign(std::string(131073, 'x')));
}
}  // namespace
int main() {
  ethernetRegression();
  shortWrites();
  boundsAndFailures();
  std::cout << "Output buffer tests passed\n";
}
