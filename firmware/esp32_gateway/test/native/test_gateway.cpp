// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include <cassert>
#include <iostream>
#include <string>
#include <vector>

#include "gateway_core.h"
using namespace platinum;
namespace {
bool contains(const std::vector<Record>& records, const std::string& payload) {
  for (const auto& r : records)
    if (r.payload == payload)
      return true;
  return false;
}
struct Fixture {
  bool save = true, accept = true;
  unsigned saves = 0, cancels = 0;
  uint16_t rf = 0x1233;
  State durable;
  std::vector<std::vector<RadioCommand>> submissions;
  Engine engine;
  Fixture()
      : engine({}, Hooks{[this](const State& s) {
                           ++saves;
                           if (save)
                             durable = s;
                           return save;
                         },
                         [this](const std::vector<RadioCommand>& c) {
                           if (accept)
                             submissions.push_back(c);
                           return accept;
                         },
                         [this]() { return ++rf; }, [this]() { ++cancels; }}) {}
  std::vector<Record> send(Session& s, const std::string& text) {
    return engine.feed(s, text);
  }
  void setup() {
    Session s;
    assert(contains(send(s, "$ar01-4-Room"), "$cr00-01-0x1234-Room"));
    assert(contains(send(s, "$as0-5-Shade"), "$cs00-00-01-Shade"));
  }
  void grant(uint32_t features = (1u << 4) | (1u << 1) | (1u << 12) | (1u << 10)) {
    State next = engine.state();
    for (auto& s : next.shades)
      s.enabled_features = features;
    assert(engine.replace(next));
  }
};
void parser_fragments() {
  const std::string cmd = "$ar01-4-Room$as0-5-Shade$dmy$dat";
  for (size_t split = 0; split <= cmd.size(); ++split) {
    Fixture f;
    Session s;
    auto a = f.send(s, cmd.substr(0, split));
    auto b = f.send(s, cmd.substr(split));
    a.insert(a.end(), b.begin(), b.end());
    assert(!s.closed);
    assert(f.engine.state().rooms.size() == 1);
    assert(f.engine.state().shades.size() == 1);
    assert(contains(a, "$ack"));
    assert(contains(a, "$upd01-"));
  }
  Fixture f;
  Session s;
  for (char c : std::string("$ar01-4-Room$as0-5-Shade"))
    f.send(s, std::string(1, c));
  assert(f.engine.state().shades.size() == 1);
  Fixture unicode;
  Session u;
  std::string text =
      "$ar1-4-A\xf0\x9f\x8c\x9e"
      "B";
  for (char c : text)
    unicode.send(u, std::string(1, c));
  assert(!u.closed);
  assert(unicode.engine.state().rooms[0].name ==
         "A\xf0\x9f\x8c\x9e"
         "B");
  Fixture bad;
  Session b;
  assert(contains(bad.send(b, "$ar1-1-\xf0\x9f\x8c\x9e"), "$error90-"));
  assert(b.closed);
  assert(bad.engine.state().rooms.empty());
  Fixture over;
  Session o;
  assert(contains(over.send(o, std::string(1025, 'x')), "$error96-"));
  assert(o.closed);
  Fixture malicious;
  Session m;
  assert(contains(malicious.send(m, "$ar1-4-AB\nD$dat"), "$error90-"));
  assert(malicious.engine.state().rooms.empty());
}
void controls() {
  Fixture f;
  f.setup();
  Session s;
  assert(contains(f.send(s, "$pss0-4-128-"), "$error92-"));
  assert(f.submissions.empty());
  f.grant();
  assert(contains(f.send(s, "$pss00-04-128"), "$done"));
  assert(f.submissions.empty());
  assert(contains(f.send(s, "-$rls"), "$act01-00-"));
  assert(f.engine.busy());
  assert(f.submissions.size() == 1);
  const auto& cmd = f.submissions[0][0];
  assert(cmd.rf_id == 0x1234 && cmd.mask == 1 && cmd.value == 128 && cmd.flags == 1);
  assert(contains(f.send(s, "$dmy"), "$ack"));
  assert(contains(f.send(s, "$as0-3-New"), "$error93-"));
  assert(contains(f.engine.complete(true), "$act00-00-"));
  assert(!f.engine.busy());
  assert(f.engine.state().shades[0].requested[0].value == 128);
  assert(contains(f.send(s, "$psr0-4-255-0-"), "$act01-00-"));
  assert(f.submissions.size() == 2);
  f.engine.complete(false);
  assert(contains(f.send(s, "$pss0-12-0-$rls"), "$done"));
  assert(f.submissions.back()[0].value == 1);
  f.engine.complete(true);
  assert(contains(f.send(s, "$rsc0-"), "$act01-00-"));
  assert(f.submissions.back()[0].flags == 3);
  f.send(s, "$stps");
  assert(f.cancels == 1);
  assert(f.engine.busy());
  f.engine.complete(false);
  assert(contains(f.send(s, "$pss0-7-0-"), "$error92-"));
  assert(contains(f.send(s, "$RepTst"), "$error91-"));
}
void staging_races() {
  Fixture f;
  f.setup();
  f.grant();
  Session a, b;
  assert(contains(f.send(a, "$pss0-4-127-"), "$done"));
  f.send(b, "$mes0-0-3-New");
  assert(contains(f.send(a, "$rls"), "$error92-"));
  assert(f.submissions.empty());
  for (size_t split = 0; split < std::string("$psr0-4-128-0-").size(); ++split) {
    Fixture room;
    room.setup();
    room.grant();
    Session s;
    std::string command = "$psr0-4-128-0-";
    room.send(s, command.substr(0, split));
    room.send(s, command.substr(split));
    assert(room.submissions.size() == 1);
  }
  Fixture old;
  old.setup();
  old.grant();
  Session s;
  assert(old.send(s, "$psr0-4-128-").empty());
  assert(contains(old.send(s, "$rls"), "$done"));
  assert(old.submissions.size() == 1);
}
void durable_failure() {
  Fixture f;
  Session s;
  f.save = false;
  assert(contains(f.send(s, "$ar1-4-Room"), "$error94-"));
  assert(f.engine.state().rooms.empty());
  f.save = true;
  f.rf = 0x1233;
  f.setup();
  f.grant();
  f.send(s, "$pss0-4-128-");
  f.save = false;
  assert(contains(f.send(s, "$rls"), "$error94-"));
  assert(f.submissions.empty());
  f.save = true;
  assert(contains(f.send(s, "$rls"), "$error92-"));
}
void scene_schedules() {
  Fixture f;
  f.setup();
  f.grant();
  Session s;
  assert(contains(f.send(s, "$am5-Night"), "$cm00-Night"));
  assert(contains(f.send(s, "$sml0-0-01-"), "$cq00-00-01-"));
  assert(f.send(s, "$mrp0-0-4-200-0-").empty());
  assert(contains(f.send(s, "$ate00-129-12-00-"), "$ca00-00-129-12-00-"));
  assert(contains(f.send(s, "$sdt10-25-01-2026-$stm11-59-59-"), "$done"));
  assert(contains(f.engine.tick(1), "$act01-00-"));
  assert(f.submissions.size() == 1);
  assert(f.durable.schedules[0].last_day == 20261025);
  f.engine.complete(true);
  assert(f.engine.tick(1).empty());
  assert(f.submissions.size() == 1);
  assert(contains(f.send(s, "$inm0-"), "$act01-00-"));
  assert(f.submissions.size() == 2);
  f.engine.complete(true);
  assert(contains(f.send(s, "$rm0-"), "$upd01-"));
  assert(f.engine.state().scenes.empty());
  assert(f.engine.state().schedules.empty());
}
void dense_indices() {
  Fixture f;
  f.setup();
  Session s;
  f.send(s, "$ar1-5-Room2$as1-6-Shade2$am5-Night$sml0-1-01-$mrp0-1-4-80-0-");
  f.grant();
  f.send(s, "$rr0-");
  const auto& st = f.engine.state();
  assert(st.rooms.size() == 1 && st.shades.size() == 1 && st.rooms[0].rf_id == 0x1235);
  assert(st.shades[0].id == 0 && st.shades[0].room == 0 && st.shades[0].slot == 1);
  assert(st.scenes[0].shades[0] == 0 && st.scenes[0].positions[0].room == 0);
  assert(Engine::validate(st));
}
void state_codec() {
  Fixture f;
  f.setup();
  f.grant();
  Session s;
  f.send(s, "$am5-Night$sml0-0-01-$mrp0-0-4-80-0-$ate0-129-12-0-$sdt10-25-1-2026-$stm12-0-0-");
  auto bytes = encodeState(f.engine.state());
  assert(!bytes.empty());
  State roundtrip;
  assert(decodeState(bytes, roundtrip));
  assert(encodeState(roundtrip) == bytes);
  for (size_t i = 0; i < bytes.size(); ++i) {
    auto corrupt = bytes;
    corrupt[i] ^= 1;
    State untouched;
    untouched.title = "Unchanged";
    assert(!decodeState(corrupt, untouched));
    assert(untouched.title == "Unchanged");
  }
  for (size_t i = 0; i < bytes.size(); ++i) {
    State decoded;
    assert(!decodeState(bytes.substr(0, i), decoded));
  }
  State bad = f.engine.state();
  bad.shades[0].slot = 9;
  assert(encodeState(bad).empty());
}
void capacity_and_replay() {
  Fixture f;
  State state;
  for (unsigned r = 0; r < 12; ++r) {
    state.rooms.push_back({uint8_t(r), 1, uint16_t(0x100 + r), "Room"});
    for (unsigned slot = 1; slot <= 8; ++slot) {
      Shade sh;
      sh.id = uint8_t(state.shades.size());
      sh.room = uint8_t(r);
      sh.slot = uint8_t(slot);
      sh.name = "Shade";
      sh.enabled_features = (1u << 4) | (1u << 10);
      sh.requested.push_back({4, 0});
      state.shades.push_back(sh);
    }
  }
  assert(f.engine.replace(state));
  Session session;
  for (unsigned id = 0; id < 96; ++id)
    assert(contains(f.send(session, "$pss" + std::to_string(id) + "-4-128-"), "$done"));
  assert(session.staged.size() == 96);
  assert(contains(f.send(session, "$psr0-10-7-$dmy"), "$error96-"));
  assert(session.staged.size() == 96);
  f.send(session, "$rls");
  assert(f.submissions.back().size() == 96);
  for (const auto& c : f.submissions.back())
    assert(c.feature == 4);
  f.engine.complete(true);
  for (unsigned id = 0; id < 10; ++id) {
    Scene sc;
    sc.id = uint8_t(id);
    sc.name = "Scene";
    for (unsigned sh = 0; sh < 96; ++sh)
      sc.shades.push_back(uint8_t(sh));
    for (unsigned room = 0; room < 12; ++room)
      sc.positions.push_back({uint8_t(room), 4, 100});
    state.scenes.push_back(sc);
  }
  assert(f.engine.replace(state));
  Session flood;
  std::string queries;
  for (unsigned i = 0; i < 256; ++i)
    queries += "$dat";
  auto records = f.send(flood, queries);
  size_t bytes = 0;
  for (const auto& r : records)
    bytes += r.payload.size() + 4;
  assert(bytes <= MaxReplyBytes);
  assert(flood.closed);
  assert(contains(records, "$error96-"));
  while (state.scenes.size() < MaxScenes) {
    auto sc = state.scenes.back();
    sc.id = uint8_t(state.scenes.size());
    state.scenes.push_back(sc);
  }
  assert(!Engine::validate(state));
  assert(encodeState(state).empty());
  Fixture schedule;
  schedule.setup();
  schedule.grant();
  Session s;
  schedule.send(
      s, "$am5-Night$sml0-0-01-$mrp0-0-4-100-0-$ate0-255-12-0-$sdt10-26-2-2026-$stm11-59-59-");
  schedule.engine.tick(1);
  assert(schedule.submissions.size() == 1);
  schedule.engine.complete(true);
  State restart = schedule.durable;
  restart.clock.day = 25;
  restart.clock.weekday = 1;
  restart.clock.second = 0;
  assert(schedule.engine.replace(restart));
  assert(schedule.engine.tick(1).empty());
  assert(schedule.submissions.size() == 1);
  schedule.send(s, "$mte0-0-255-12-0-");
  assert(schedule.engine.state().schedules[0].last_day == 20261026);
}
void malformed_corpus() {
  uint32_t seed = 0x12345678;
  for (unsigned trial = 0; trial < 2000; ++trial) {
    Fixture f;
    Session s;
    std::string input;
    size_t length = trial % 128;
    for (size_t j = 0; j < length; ++j) {
      seed = seed * 1664525u + 1013904223u;
      input.push_back(char(seed >> 24));
    }
    for (char c : input)
      f.send(s, std::string(1, c));
    assert(Engine::validate(f.engine.state()));
  }
  const char* bad[] = {"$pss0-4-9999-",    "$pss10000-4-0-",
                       "$sdt2-30-1-2026-", "$stm24-0-0-",
                       "$sml0-0-2-",       "$ar1-26-abcdefghijklmnopqrstuvwxyz",
                       "$ar1-1-\xc0\xaf",  "$ar1-1-\xed\xa0\x80"};
  for (const char* input : bad) {
    Fixture f;
    Session s;
    auto reply = f.send(s, input);
    assert(!reply.empty());
    assert(f.submissions.empty());
    assert(f.engine.state().rooms.empty());
  }
}

void transaction_preview() {
  Fixture f;
  f.setup();
  f.grant();
  auto before = encodeState(f.engine.state());
  unsigned saved = f.saves;
  assert(validateTransaction(f.engine.state(), "$pss0-4-128-$rls"));
  assert(!validateTransaction(f.engine.state(), "$pss0-4-128-"));
  assert(!validateTransaction(f.engine.state(), "$ar1-4-Room$unknown"));
  assert(!validateTransaction(f.engine.state(), "$ar1-4-Room$pss99-4-128-$rls"));
  assert(!validateTransaction(f.engine.state(), "$ar1-4-Room$as0-5-Shorter"));
  assert(!validateTransaction(f.engine.state(), "$pss0-4-128-$rls$pss0-4-0-$rls"));
  assert(validateTransaction(f.engine.state(), "$stps"));
  assert(validateTransaction(f.engine.state(), "$am5-Night$sml0-0-01-$mrp0-0-4-128-0-"));
  assert(f.submissions.empty() && f.saves == saved && encodeState(f.engine.state()) == before);
}

}  // namespace
int main() {
  parser_fragments();
  controls();
  staging_races();
  durable_failure();
  scene_schedules();
  dense_indices();
  state_codec();
  capacity_and_replay();
  malformed_corpus();
  transaction_preview();
  std::cout << "gateway native tests passed\n";
}
