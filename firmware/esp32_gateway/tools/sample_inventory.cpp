// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
// Emit one PGW1 hexadecimal line for the firmware's USB "import HEX" command.
// Identities, names and requested positions are synthetic; no hardware is used.
#include <iomanip>
#include <iostream>

#include "gateway_core.h"

int main(int argc, char**) {
  if (argc != 1) {
    std::cerr << "sample_inventory takes no arguments\n";
    return 2;
  }
  platinum::State state;
  state.mac = "020000000001";
  state.rooms = {{0, 1, 0x1234, "Bottom-up"}, {1, 2, 0x5678, "Dual rail"},
                 {2, 3, 0x9abc, "Top-down"}, {3, 6, 0xabcd, "Sheers"}};
  const char* names[] = {"East window", "West window", "Left shade",
                         "Right shade", "Desk window", "Door shade", "Front sheer", "Side sheer"};
  const uint8_t positions[] = {0, 128, 255, 64, 192, 0, 128, 0};
  for (uint8_t id = 0; id < 8; ++id) {
    platinum::Shade shade;
    shade.id = id;
    shade.room = id / 2;
    shade.slot = id % 2 + 1;
    shade.name = names[id];
    shade.enabled_features = (1u << 4) | (1u << 10);
    shade.requested = {{4, positions[id]}};
    shade.last_requested_feature = 4;  // Explicit fictional chronology.
    // Explicit fictional installation facts, not derived from product codes.
    shade.controls = {{4, platinum::ControlRole::Lift, platinum::EndpointMapping::OpenAt255}};
    if (id == 2 || id == 3) {
      shade.enabled_features |= 1u << 18;
      shade.requested.push_back({18, 64});
      shade.controls = {{4, platinum::ControlRole::BottomRail, platinum::EndpointMapping::OpenAt255},
                         {18, platinum::ControlRole::TopRail, platinum::EndpointMapping::OpenAt255}};
    } else if (id == 4 || id == 5)
      shade.controls = {{4, platinum::ControlRole::TopRail, platinum::EndpointMapping::OpenAtZero}};
    else if (id == 6 || id == 7) {
      shade.enabled_features |= (1u << 7) | (1u << 19);
      shade.requested.push_back({7, 128});
      shade.requested.push_back({19, 128});
    }
    state.shades.push_back(shade);
  }
  if (!platinum::Engine::validate(state)) {
    std::cerr << "Invalid sample state\n";
    return 1;
  }
  const auto encoded = platinum::encodeState(state);
  if (encoded.empty()) {
    std::cerr << "Could not encode sample state\n";
    return 1;
  }
  std::cout << std::hex << std::setfill('0');
  for (unsigned char byte : encoded)
    std::cout << std::setw(2) << unsigned(byte);
  std::cout << '\n';
  return std::cout ? 0 : 1;
}
