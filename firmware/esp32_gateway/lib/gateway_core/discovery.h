// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

#include <array>
#include <cstddef>
#include <cstdint>
#include <vector>

namespace platinum {

// Pure, bounded NBNS responder. Empty means an unrelated or malformed query.
// The network adapter owns subnet restrictions, rate limiting and UDP port 137.
std::vector<uint8_t> discoveryResponse(const uint8_t* data, size_t size,
                                       const std::array<uint8_t, 4>& ip);

}  // namespace platinum
