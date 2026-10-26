// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <limits>
#include <string_view>

namespace platinum {
namespace serial {

// Parse an exact command followed by N unsigned decimal arguments. Spaces and
// tabs separate tokens; leading zeroes and trailing separators are permitted.
// A malformed command leaves output unchanged, including on integer overflow.
template <size_t N>
bool unsignedArguments(std::string_view line, std::string_view command_name,
                       std::array<uint32_t, N>& output) {
  const auto separator = [](char c) { return c == ' ' || c == '\t'; };
  if (command_name.empty() || command_name.find_first_of(" \t\r\n") != std::string_view::npos ||
      line.substr(0, command_name.size()) != command_name)
    return false;
  size_t at = command_name.size();
  if (at < line.size() && !separator(line[at]))
    return false;
  std::array<uint32_t, N> parsed{};
  for (auto& value : parsed) {
    while (at < line.size() && separator(line[at]))
      ++at;
    if (at == line.size() || line[at] < '0' || line[at] > '9')
      return false;
    while (at < line.size() && line[at] >= '0' && line[at] <= '9') {
      const uint32_t digit = static_cast<uint32_t>(line[at] - '0');
      if (value > (std::numeric_limits<uint32_t>::max() - digit) / 10)
        return false;
      value = value * 10 + digit;
      ++at;
    }
    if (at < line.size() && !separator(line[at]))
      return false;
  }
  while (at < line.size() && separator(line[at]))
    ++at;
  if (at != line.size())
    return false;
  output = parsed;
  return true;
}

}  // namespace serial
}  // namespace platinum
