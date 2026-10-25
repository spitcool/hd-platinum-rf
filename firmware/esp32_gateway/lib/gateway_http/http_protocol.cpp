// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include "http_protocol.h"

#include <algorithm>
#include <cstdint>
#include <set>
#include <utility>
namespace platinum {
namespace http {
namespace {
std::string lower(std::string text) {
  for (auto& c : text)
    if (c >= 'A' && c <= 'Z')
      c = char(c - 'A' + 'a');
  return text;
}
bool tokenChar(unsigned char c) {
  return (c >= 'a' && c <= 'z') || (c >= 'A' && c <= 'Z') || (c >= '0' && c <= '9') ||
         std::string("!#$%&'*+-.^_`|~").find(char(c)) != std::string::npos;
}
bool singleton(const std::string& key) {
  return key == "host" || key == "content-length" || key == "authorization" || key == "origin" ||
         key == "content-type";
}
}  // namespace
std::string Request::header(const std::string& name) const {
  auto key = lower(name);
  for (const auto& pair : headers)
    if (pair.first == key)
      return pair.second;
  return {};
}
size_t Request::headerCount(const std::string& name) const {
  auto key = lower(name);
  size_t count = 0;
  for (const auto& pair : headers)
    if (pair.first == key)
      ++count;
  return count;
}
ParseResult parse(const std::string& buffer, Request& output) {
  if (buffer.size() > MaxRequest)
    return ParseResult::TooLarge;
  const size_t boundary = buffer.find("\r\n\r\n");
  const size_t headerEnd = boundary == std::string::npos ? buffer.size() : boundary + 4;
  if (headerEnd > MaxHeaders)
    return ParseResult::TooLarge;
  // Inspect partial headers as they arrive, including split CRLF sequences.
  for (size_t i = 0; i < headerEnd; ++i) {
    unsigned char c = uint8_t(buffer[i]);
    if (c == 0 || c == 127 || (c < 32 && c != '\r' && c != '\n' && c != '\t'))
      return ParseResult::Invalid;
    if (c == '\n' && (i == 0 || buffer[i - 1] != '\r'))
      return ParseResult::Invalid;
    if (c == '\r' && i + 1 < headerEnd && buffer[i + 1] != '\n')
      return ParseResult::Invalid;
  }
  if (boundary == std::string::npos)
    return ParseResult::Incomplete;
  Request request;
  const size_t first = buffer.find("\r\n");
  if (first == 0 || first > boundary)
    return ParseResult::Invalid;
  const std::string line = buffer.substr(0, first);
  const size_t space = line.find(' '), last = line.rfind(' ');
  if (space == std::string::npos || space == last || line.substr(last + 1) != "HTTP/1.1")
    return ParseResult::Invalid;
  request.method = line.substr(0, space);
  request.path = line.substr(space + 1, last - space - 1);
  if (request.method != "GET" && request.method != "POST" && request.method != "PATCH")
    return ParseResult::Invalid;
  if (request.path.empty() || request.path[0] != '/')
    return ParseResult::Invalid;
  for (unsigned char c : request.path)
    if (c < 33 || c > 126 || c == '#')
      return ParseResult::Invalid;
  size_t length = 0;
  bool hasLength = false;
  std::set<std::string> singletons;
  for (size_t at = first + 2; at < boundary;) {
    size_t end = buffer.find("\r\n", at);
    if (end == std::string::npos || end > boundary)
      return ParseResult::Invalid;
    size_t colon = buffer.find(':', at);
    if (colon == std::string::npos || colon >= end || colon == at)
      return ParseResult::Invalid;
    for (size_t i = at; i < colon; ++i)
      if (!tokenChar(uint8_t(buffer[i])))
        return ParseResult::Invalid;
    auto key = lower(buffer.substr(at, colon - at));
    if (key == "transfer-encoding")
      return ParseResult::Invalid;
    if (singleton(key) && !singletons.insert(key).second)
      return ParseResult::Invalid;
    size_t begin = colon + 1, valueEnd = end;
    while (begin < valueEnd && (buffer[begin] == ' ' || buffer[begin] == '\t'))
      ++begin;
    while (valueEnd > begin && (buffer[valueEnd - 1] == ' ' || buffer[valueEnd - 1] == '\t'))
      --valueEnd;
    auto value = buffer.substr(begin, valueEnd - begin);
    if (key == "host") {
      if (value.empty())
        return ParseResult::Invalid;
      for (unsigned char c : value)
        if (c <= 32 || c >= 127 || c == '/' || c == '\\' || c == '@' || c == ',' || c == '#')
          return ParseResult::Invalid;
    }
    if (key == "content-length") {
      if (value.empty())
        return ParseResult::Invalid;
      hasLength = true;
      for (unsigned char c : value) {
        if (c < '0' || c > '9')
          return ParseResult::Invalid;
        if (length > MaxBody / 10 || (length == MaxBody / 10 && unsigned(c - '0') > MaxBody % 10))
          return ParseResult::TooLarge;
        length = length * 10 + unsigned(c - '0');
      }
    }
    if (request.headers.size() >= 64)
      return ParseResult::TooLarge;
    request.headers.emplace_back(std::move(key), std::move(value));
    at = end + 2;
  }
  if (singletons.count("host") != 1)
    return ParseResult::Invalid;
  if (request.method != "GET" && !hasLength)
    return ParseResult::Invalid;
  if (request.method == "GET" && length)
    return ParseResult::Invalid;
  const size_t expected = boundary + 4 + length;
  if (expected > MaxRequest)
    return ParseResult::TooLarge;
  if (buffer.size() < expected)
    return ParseResult::Incomplete;
  if (buffer.size() != expected)
    return ParseResult::Invalid;
  request.body = buffer.substr(boundary + 4, length);
  for (unsigned char c : request.body)
    if (c == 0 || c == 127 || (c < 32 && c != '\r' && c != '\n' && c != '\t'))
      return ParseResult::Invalid;
  output = std::move(request);
  return ParseResult::Complete;
}
bool authorizedBearer(const std::string& token, const std::string& authorization) {
  if (token.size() < 32)
    return false;
  // Runtime depends only on the configured token length, not a matching prefix.
  const std::string expected = "Bearer " + token;
  size_t difference = authorization.size() ^ expected.size();
  for (size_t i = 0; i < expected.size(); ++i)
    difference |= uint8_t(expected[i]) ^ uint8_t(i < authorization.size() ? authorization[i] : 0);
  return difference == 0;
}
}  // namespace http
}  // namespace platinum
