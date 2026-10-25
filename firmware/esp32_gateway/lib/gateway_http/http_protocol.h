// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <string>
#include <utility>
#include <vector>
namespace platinum {
namespace http {
constexpr size_t MaxHeaders = 4096, MaxBody = 4096, MaxRequest = 8192;
struct Request {
  std::string method, path, body;
  // Names are normalized to lowercase. Values have surrounding SP/HTAB removed.
  std::vector<std::pair<std::string, std::string>> headers;
  std::string header(const std::string& name) const;
  size_t headerCount(const std::string& name) const;
};
enum class ParseResult { Incomplete, Complete, Invalid, TooLarge };
// One strict HTTP/1.1 request. No pipelining, transfer coding, duplicate framing
// or authentication headers. Output changes only on Complete.
ParseResult parse(const std::string& buffer, Request& output);
bool authorizedBearer(const std::string& token, const std::string& authorization);
}  // namespace http
}  // namespace platinum
