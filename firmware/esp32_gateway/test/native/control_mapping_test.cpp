// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include "gateway_core.h"
#include <cassert>
#include <iostream>

using namespace platinum;
namespace {
State fixture() {
  State s;
  s.rooms = {{0, 2, 0x1234, "Mixed directions"}, {1, 1, 0x2345, "Other"}};
  s.shades = {{0, 0, 1, "Top", (1u << 4) | (1u << 18), {{4, 128}}, {}},
              {1, 0, 2, "Lift", (1u << 4) | (1u << 18), {{4, 64}}, {}}};
  return s;
}
void catalog_and_unknowns() {
  const uint8_t known[] = {0,1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16,17,18,21,22,23,24,25,30};
  for (auto code : known) {
    assert(productSupportsFeature(code, 4));
    assert(productSupportsFeature(code, 18) == (code == 2 || code == 13 || code == 25));
    assert(productSupportsFeature(code, 7) == (code == 6 || code == 8 || code == 9 || code == 10));
    assert(productSupportsFeature(code, 19) == (code == 6 || code == 8));
    assert(productSupportsFeature(code, 10));
    assert(!productSupportsFeature(code, 24)); // Hex0x18 is not decimal18.
  }
  assert(!productFeatureMask(255));
  auto s = fixture();
  uint8_t value = 99;
  assert(controlLabel(s.shades[0], 4) == "Primary");
  assert(controlLabel(s.shades[0], 18) == "Secondary");
  assert(!endpointValue(s.shades[0], 4, true, value) && value == 99);
  assert(endpointTransaction(s, 0, false, 4, true).empty());
  assert(rawControlTransaction(s, 0, false, 18, 127) == "$pss00-18-127-$rls");
  assert(rawControlTransaction(s, 0, false, 18, 127, 1u << 4).empty());
  assert(!featureAvailable(s, s.shades[0], 18, 1u << 4));
  assert(rawControlTransaction(s, 0, false, 7, 128).empty());
  assert(rawControlTransaction(s, 1, true, 4, 128).empty()); // Empty room.
}
void explicit_directions_and_group_atomicity() {
  auto s = fixture();
  s.shades[0].controls = {{4, ControlRole::TopRail, EndpointMapping::OpenAtZero},
                          {18, ControlRole::BottomRail, EndpointMapping::OpenAt255}};
  s.shades[1].controls = {{4, ControlRole::Lift, EndpointMapping::OpenAt255}};
  assert(Engine::validate(s));
  assert(controlLabel(s.shades[0], 4) == "Top rail");
  assert(endpointTransaction(s, 0, true, 4, true) == "$pss00-04-000-$pss01-04-255-$rls");
  assert(endpointTransaction(s, 0, true, 4, false) == "$pss00-04-255-$pss01-04-000-$rls");
  assert(endpointTransaction(s, 0, true, 18, true).empty()); // One member unknown.
  assert(rawControlTransaction(s, 0, true, 18, 129) == "$pss00-18-129-$pss01-18-129-$rls");
  std::vector<RadioCommand> sent;
  Engine e(s, Hooks{[](const State&) { return true; }, [&](const auto& commands) {
    sent = commands; return true;
  }, {}, {}});
  Session session;
  e.feed(session, endpointTransaction(s, 0, true, 4, true));
  assert(sent.size() == 2 && sent[0].value == 0 && sent[1].value == 255);
  assert(sent[0].mask == 1 && sent[1].mask == 2 && sent[0].feature == 4);
  s.shades[1].enabled_features = 0;
  assert(endpointTransaction(s, 0, true, 4, true).empty());
  assert(rawControlTransaction(s, 0, true, 4, 128).empty());
  // A configured mapping is not a grant, and is not limited to a product's UI name.
  s.rooms[0].product = 1;
  s.shades[0].controls.resize(1);
  assert(Engine::validate(s));
  assert(controlLabel(s.shades[0], 4) == "Top rail");
}
void codec_migration_and_validation() {
  // Independent retained schema1 fixture: identity/slot, grants, both requested
  // channels, scene, schedule, title, clock and generation must all survive.
  const char* hex = "50475731010000000c0000004906004c65676163790c00303230303030303030303031ea070a19010c223801010100000234120400526f6f6d0100000002050053686164651000040002000481121701000005005363656e65010000010000122a01000000ff0d0ca1283501cb657141";
  std::string bytes;
  for (size_t i = 0; hex[i]; i += 2)
    bytes.push_back(char(std::stoul(std::string(hex + i, 2), nullptr, 16)));
  State s;
  assert(decodeState(bytes, s));
  assert(s.schema == 3 && s.generation == 12 && s.led == 73 && s.title == "Legacy");
  assert(s.mac == "020000000001" && s.clock.year == 2026 && s.clock.second == 56);
  assert(s.rooms[0].rf_id == 0x1234 && s.shades[0].slot == 2);
  assert(s.shades[0].enabled_features == ((1u << 4) | (1u << 18)));
  assert(s.shades[0].controls.empty() && s.shades[0].requested.size() == 2);
  assert(s.shades[0].requested[0].value == 129 && s.shades[0].requested[1].value == 23);
  assert(!s.shades[0].last_requested_feature); // Legacy vector order is not chronology.
  assert(s.scenes[0].positions[0].feature == 18 && s.scenes[0].positions[0].value == 42);
  assert(s.schedules[0].last_day == 20261025 && s.schedules[0].days == 255);
  s.shades[0].controls = {{4, ControlRole::TopRail, EndpointMapping::OpenAtZero},
                          {18, ControlRole::BottomRail, EndpointMapping::OpenAt255}};
  auto encoded = encodeState(s);
  assert(encoded != bytes && uint8_t(encoded[4]) == 3);
  State roundtrip;
  assert(decodeState(encoded, roundtrip) && encodeState(roundtrip) == encoded);
  assert(controlLabel(roundtrip.shades[0], 18) == "Bottom rail");
  for (size_t i = 0; i < encoded.size(); ++i) {
    auto corrupt = encoded; corrupt[i] ^= 1;
    assert(!decodeState(corrupt, roundtrip));
  }
  auto bad = s;
  bad.shades[0].controls[1].feature = 4;
  assert(!Engine::validate(bad));
  bad = s; bad.shades[0].controls[0].feature = 7;
  assert(!Engine::validate(bad));
  bad = s; bad.shades[0].controls[0].role = static_cast<ControlRole>(255);
  assert(!Engine::validate(bad));
  bad = s; bad.shades[0].controls[0].endpoints = static_cast<EndpointMapping>(255);
  assert(!Engine::validate(bad));
}
void invalidation_and_feature_values() {
  auto s = fixture();
  s.shades[0].last_requested_feature = 4;
  s.shades[0].controls = {{4, ControlRole::TopRail, EndpointMapping::OpenAtZero}};
  Engine e(s, Hooks{[](const State&) { return true; }, {}, {}, {}});
  Session session;
  e.feed(session, "$mes0-0-7-Renamed");
  assert(e.state().shades[0].controls.size() == 1);
  assert(isLatestRequestedFeature(e.state().shades[0], 4));
  e.feed(session, "$mer0-2-7-Renamed");
  assert(e.state().shades[0].controls.size() == 1);
  e.feed(session, "$mer0-1-7-Renamed");
  assert(e.state().shades[0].controls.empty() && !e.state().shades[0].enabled_features);
  assert(e.replace(s));
  e.feed(session, "$mes0-1-7-Renamed");
  assert(e.state().shades[0].controls.empty() && !e.state().shades[0].enabled_features);
  assert(e.state().shades[0].requested.empty() && !e.state().shades[0].last_requested_feature);
  for (uint8_t f : {4, 18, 7, 19, 10}) {
    auto p = fixture();
    p.rooms[0].product = (f == 7 || f == 19) ? 6 : 2;
    p.shades[0].enabled_features = 1u << f;
    uint8_t v = f == 10 ? 7 : 129;
    auto command = rawControlTransaction(p, 0, false, f, v);
    assert(!command.empty() && validateTransaction(p, command));
    if (f == 10) assert(rawControlTransaction(p, 0, false, f, 128).empty());
  }
}
void schema2_migration_retains_maps_but_never_invents_order() {
  // Retained output of the schema2 sample-inventory tool used by an actual
  // instruction-emulator run before schema3. Includes single and multi-feature
  // histories and explicitly configured endpoint mappings of both directions.
  const char* hex =
      "504757310200000000000000000800506c6174696e756d0c00303230303030303030303031000000000000000000000400000134120900426f74746f6d2d75700102785609004475616c207261696c0203bc9a0800546f702d646f776e0306cdab060053686565727308000000010b00456173742077696e646f771004000001000400010401020100020b00576573742077696e646f771004000001000480010401020201010a004c65667420736861646510040400020004ff1240020403021202010301020b00526967687420736861646510040400020004401240020403021202010402010b004465736b2077696e646f7710040000010004c0010402010502020a00446f6f722073686164651004000001000400010402010603010b0046726f6e74207368656572900408000300048007801380010401020703020a00536964652073686565729004080003000400078013800104010200000000a1aa70b9";
  std::string bytes;
  for (size_t i = 0; hex[i]; i += 2)
    bytes.push_back(char(std::stoul(std::string(hex + i, 2), nullptr, 16)));
  State migrated;
  assert(decodeState(bytes, migrated) && migrated.schema == 3);
  assert(migrated.rooms.size() == 4 && migrated.shades.size() == 8);
  assert(isLatestRequestedFeature(migrated.shades[0], 4));
  assert(isLatestRequestedFeature(migrated.shades[4], 4));
  assert(!migrated.shades[2].last_requested_feature);
  assert(!migrated.shades[6].last_requested_feature);
  assert(migrated.shades[2].requested.size() == 2 && migrated.shades[6].requested.size() == 3);
  uint8_t value;
  assert(endpointValue(migrated.shades[2], 18, true, value) && value == 0);
  assert(endpointValue(migrated.shades[0], 4, true, value) && value == 255);
  unsigned secondShadeRecords = 0;
  for (const auto& record : Engine(migrated).snapshot())
    secondShadeRecords += record.payload.rfind("$cp02-", 0) == 0;
  assert(secondShadeRecords == 0); // An ambiguous legacy order is not replayed.
  const auto encoded = encodeState(migrated);
  State restored;
  assert(decodeState(encoded, restored) && encodeState(restored) == encoded);
  assert(!restored.shades[2].last_requested_feature);
  migrated.shades[2].last_requested_feature = 18;
  assert(decodeState(encodeState(migrated), restored));
  assert(lastRequestedPosition(restored.shades[2])->feature == 18);
  assert(lastRequestedPosition(restored.shades[2])->value == 64);
  auto invalid = migrated;
  invalid.shades[2].last_requested_feature = 7;
  assert(!Engine::validate(invalid) && encodeState(invalid).empty());
  invalid.shades[2].last_requested_feature = 255;
  assert(!Engine::validate(invalid));
  invalid = migrated;
  invalid.schema = 2;
  assert(encodeState(invalid).empty()); // Never silently write a changed schema2.
}
} // namespace
int main() {
  catalog_and_unknowns();
  explicit_directions_and_group_atomicity();
  codec_migration_and_validation();
  invalidation_and_feature_values();
  schema2_migration_retains_maps_but_never_invents_order();
  std::cout << "Explicit control mapping, group routing and schema migration passed\n";
}
