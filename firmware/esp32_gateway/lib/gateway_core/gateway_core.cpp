// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include "gateway_core.h"

#include <algorithm>
#include <array>
#include <cstdio>
#include <limits>
#include <set>
#include <utility>

namespace platinum {
namespace {
constexpr uint32_t Features =
    (1u << 1) | (1u << 4) | (1u << 7) | (1u << 10) | (1u << 12) | (1u << 18) | (1u << 19);
std::string dec(unsigned n, unsigned width = 2) {
  char b[16];
  std::snprintf(b, sizeof b, "%0*u", int(width), n);
  return b;
}
std::vector<Record> err(unsigned n = 90) {
  return {{false, "$error" + dec(n) + "-"}};
}
bool product(unsigned n) {
  return n <= 18 || (n >= 21 && n <= 25) || n == 30;
}
bool feature(unsigned n) {
  return n < 32 && (Features & (1u << n));
}
bool control(unsigned n) {
  return n == 4 || n == 7 || n == 10 || n == 18 || n == 19;
}
bool leap(unsigned n) {
  return n % 4 == 0 && (n % 100 != 0 || n % 400 == 0);
}
unsigned monthDays(unsigned year, unsigned month) {
  static const uint8_t d[] = {31, 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31};
  return month >= 1 && month <= 12 ? d[month - 1] + (month == 2 && leap(year)) : 0;
}
bool date(unsigned year, unsigned month, unsigned day, unsigned week) {
  return year >= 2000 && year <= 9999 && week >= 1 && week <= 7 && day >= 1 &&
         day <= monthDays(year, month);
}
// Return byte count for exactly `units` UTF-16 code units: -1 incomplete, -2 invalid.
int nameEnd(const std::string& s, size_t at, unsigned units) {
  if (units < 1 || units > 25)
    return -2;
  unsigned seen = 0;
  size_t start = at;
  while (seen < units) {
    if (at == s.size())
      return -1;
    auto b = static_cast<uint8_t>(s[at]);
    unsigned count = 0, cp = 0, min = 0;
    if (b < 0x80) {
      count = 1;
      cp = b;
    } else if (b >= 0xc2 && b <= 0xdf) {
      count = 2;
      cp = b & 31;
      min = 0x80;
    } else if (b >= 0xe0 && b <= 0xef) {
      count = 3;
      cp = b & 15;
      min = 0x800;
    } else if (b >= 0xf0 && b <= 0xf4) {
      count = 4;
      cp = b & 7;
      min = 0x10000;
    } else
      return -2;
    if (at + count > s.size())
      return -1;
    for (unsigned j = 1; j < count; ++j) {
      auto c = static_cast<uint8_t>(s[at + j]);
      if ((c & 0xc0) != 0x80)
        return -2;
      cp = (cp << 6) | (c & 63);
    }
    if (cp < min || cp > 0x10ffff || (cp >= 0xd800 && cp <= 0xdfff) || cp < 32 || cp == 127)
      return -2;
    seen += cp > 0xffff ? 2 : 1;
    if (seen > units)
      return -2;
    at += count;
  }
  return int(at - start);
}
bool name(const std::string& s) {
  if (s.empty() || s.size() > 100 || s.find_first_not_of(" \t") == std::string::npos)
    return false;
  for (unsigned n = 1; n <= 25; ++n)
    if (nameEnd(s, 0, n) == int(s.size()))
      return true;
  return false;
}
std::string roomRecord(const Room& r) {
  char hex[5];
  std::snprintf(hex, sizeof hex, "%04x", r.rf_id);
  return "$cr" + dec(r.id) + "-" + dec(r.product) + "-0x" + hex + "-" + r.name;
}
std::string shadeRecord(const Shade& s) {
  return "$cs" + dec(s.id) + "-" + dec(s.room) + "-" + dec(s.slot) + "-" + s.name;
}
std::string cp(unsigned shade, unsigned f, unsigned v) {
  return "$cp" + dec(shade) + "-" + dec(f) + "-" + dec(v, 3) + "-";
}
std::string sceneRecord(const Scene& s) {
  return "$cm" + dec(s.id) + "-" + s.name;
}
std::string scheduleRecord(const Schedule& s) {
  return "$ca" + dec(s.id) + "-" + dec(s.scene) + "-" + dec(s.days, 3) + "-" + dec(s.hour) + "-" +
         dec(s.minute) + "-";
}
void setPosition(Shade& shade, uint8_t f, uint8_t v) {
  for (auto& p : shade.requested)
    if (p.feature == f) {
      p.value = v;
      return;
    }
  shade.requested.push_back({f, v});
}
// Conservative wire budget includes a one-digit session prefix and LF CR.
size_t snapshotBudget(const State& s) {
  size_t bytes = 256 + s.title.size();
  for (const auto& r : s.rooms)
    bytes += 20 + r.name.size();
  for (const auto& sh : s.shades)
    bytes += 16 + sh.name.size() + 20 * sh.requested.size();
  for (const auto& sc : s.scenes)
    bytes += 10 + sc.name.size() + 16 * sc.shades.size() + 25 * sc.positions.size();
  bytes += 23 * s.schedules.size();
  return bytes;
}
struct Grammar {
  const char* token;
  uint8_t fields;
  bool named = false;
  bool optional = false;
};
const Grammar GrammarTable[] = {{"$chksy", 1},     {"$RepTst", 0},    {"$BdgBtl", 0},
                                {"$LEDl", 1},      {"$stps", 0},      {"$dat", 0},
                                {"$dmy", 0},       {"$rls", 0},       {"$sdt", 4},
                                {"$stm", 3},       {"$mer", 3, true}, {"$mes", 3, true},
                                {"$cmn", 2, true}, {"$rsc", 1},       {"$pss", 3, false, true},
                                {"$psr", 4},       {"$mrp", 5},       {"$sml", 3},
                                {"$inm", 1},       {"$ate", 4},       {"$mte", 5},
                                {"$rte", 1},       {"$ar", 2, true},  {"$as", 2, true},
                                {"$am", 1, true},  {"$rr", 1},        {"$rs", 1},
                                {"$rm", 1}};
// Independent scene/index maintenance. LAN IDs are dense for the original APK;
// RF identity and slot are physical bindings and survive numeric compaction.
void removeShade(State& s, size_t index) {
  s.shades.erase(s.shades.begin() + index);
  for (size_t i = 0; i < s.shades.size(); ++i)
    s.shades[i].id = uint8_t(i);
  for (auto& scene : s.scenes) {
    scene.shades.erase(std::remove(scene.shades.begin(), scene.shades.end(), index),
                       scene.shades.end());
    for (auto& id : scene.shades)
      if (id > index)
        --id;
  }
}
void removeScene(State& s, size_t index) {
  s.scenes.erase(s.scenes.begin() + index);
  for (size_t i = 0; i < s.scenes.size(); ++i)
    s.scenes[i].id = uint8_t(i);
  s.schedules.erase(std::remove_if(s.schedules.begin(), s.schedules.end(),
                                   [index](const Schedule& x) { return x.scene == index; }),
                    s.schedules.end());
  for (size_t i = 0; i < s.schedules.size(); ++i) {
    s.schedules[i].id = uint8_t(i);
    if (s.schedules[i].scene > index)
      --s.schedules[i].scene;
  }
}
unsigned freeSlot(const State& s, unsigned room) {
  unsigned mask = 0;
  for (const auto& shade : s.shades)
    if (shade.room == room)
      mask |= 1u << (shade.slot - 1);
  for (unsigned i = 1; i <= 8; ++i)
    if (!(mask & (1u << (i - 1))))
      return i;
  return 0;
}
bool productFeature(unsigned product, unsigned f) {
  if (f == 1 || f == 4 || f == 10 || f == 12)
    return true;
  if (f == 18)
    return product == 2 || product == 13 || product == 25;
  if (f == 7)
    return product == 6 || product == 8 || product == 9 || product == 10;
  return f == 19 && (product == 6 || product == 8);
}
}  // namespace

Engine::Engine(State initial, Hooks hooks)
    : state_(std::move(initial)), hooks_(std::move(hooks)), valid_(validate(state_)) {}
bool Engine::validate(const State& s) {
  if (snapshotBudget(s) > MaxSnapshotBytes || s.schema != 1 || s.rooms.size() > MaxRooms ||
      s.shades.size() > MaxShades || s.scenes.size() > MaxScenes ||
      s.schedules.size() > MaxSchedules || !name(s.title) || s.mac.size() != 12)
    return false;
  for (char c : s.mac)
    if (!((c >= '0' && c <= '9') || (c >= 'a' && c <= 'f') || (c >= 'A' && c <= 'F')))
      return false;
  std::set<uint16_t> ids;
  for (size_t i = 0; i < s.rooms.size(); ++i) {
    const auto& r = s.rooms[i];
    if (r.id != i || !product(r.product) || !name(r.name) || !r.rf_id ||
        !ids.insert(r.rf_id).second)
      return false;
  }
  std::array<unsigned, MaxRooms> slots{};
  for (size_t i = 0; i < s.shades.size(); ++i) {
    const auto& sh = s.shades[i];
    if (sh.id != i || sh.room >= s.rooms.size() || sh.slot < 1 || sh.slot > 8 || !name(sh.name) ||
        (sh.enabled_features & ~Features))
      return false;
    unsigned bit = 1u << (sh.slot - 1);
    if (slots[sh.room] & bit)
      return false;
    slots[sh.room] |= bit;
    unsigned features = 0;
    for (const auto& p : sh.requested) {
      if (!control(p.feature) || (features & (1u << p.feature)))
        return false;
      features |= 1u << p.feature;
    }
  }
  for (size_t i = 0; i < s.scenes.size(); ++i) {
    const auto& sc = s.scenes[i];
    if (sc.id != i || !name(sc.name) || sc.shades.size() > MaxShades ||
        sc.positions.size() > MaxRooms * 5)
      return false;
    std::set<unsigned> linked, positions;
    for (auto sh : sc.shades)
      if (sh >= s.shades.size() || !linked.insert(sh).second)
        return false;
    for (const auto& p : sc.positions)
      if (p.room >= s.rooms.size() || !control(p.feature) || (p.feature == 10 && p.value != 7) ||
          !productFeature(s.rooms[p.room].product, p.feature) ||
          !positions.insert(unsigned(p.room) * 32 + p.feature).second)
        return false;
  }
  for (size_t i = 0; i < s.schedules.size(); ++i) {
    const auto& e = s.schedules[i];
    if (e.id != i || e.scene >= s.scenes.size() || e.hour > 23 || e.minute > 59)
      return false;
  }
  const auto& c = s.clock;
  return (!c.date_valid || date(c.year, c.month, c.day, c.weekday)) &&
         (!c.time_valid || (c.hour <= 23 && c.minute <= 59 && c.second <= 59));
}
bool Engine::commit(State candidate) {
  if (!validate(candidate) || !hooks_.persist || !hooks_.persist(candidate))
    return false;
  state_ = std::move(candidate);
  valid_ = true;
  return true;
}
bool Engine::replace(State s) {
  if (busy_)
    return false;
  s.generation = state_.generation + 1;
  return commit(std::move(s));
}
std::vector<Record> Engine::snapshot() const {
  if (!valid_)
    return err(94);
  std::vector<Record> out;
  auto add = [&](std::string s) { out.push_back({false, std::move(s)}); };
  add("$firm03-Platinum ESP32 gateway 0.1");
  add("$MAC0x" + state_.mac + "-");
  add("$LEDl" + dec(state_.led, 3) + "-");
  add("$upd00-");
  add("$reset");
  add("$ct" + state_.title);
  for (const auto& r : state_.rooms)
    add(roomRecord(r));
  for (const auto& s : state_.shades) {
    add(shadeRecord(s));
    for (const auto& p : s.requested)
      add(cp(s.id, p.feature, p.value));
  }
  for (const auto& s : state_.scenes) {
    add(sceneRecord(s));
    for (auto sh : s.shades)
      add("$cq" + dec(s.id) + "-" + dec(sh) + "-01-");
    for (const auto& p : s.positions)
      add("$cx" + dec(s.id) + "-" + dec(p.room) + "-" + dec(p.feature) + "-" + dec(p.value, 3) +
          "-00-");
  }
  for (const auto& s : state_.schedules)
    add(scheduleRecord(s));
  add("$upd01-");
  return out;
}
std::vector<Record> Engine::feed(Session& session, const std::string& bytes) {
  if (session.closed)
    return {};
  if (bytes.size() > MaxInput || session.pending.size() + bytes.size() > MaxInput) {
    session.pending.clear();
    session.staged.clear();
    session.closed = true;
    return err(96);
  }
  session.pending += bytes;
  std::vector<Record> out;
  size_t outputBytes = 0;
  auto fail = [&]() {
    session.pending.clear();
    session.staged.clear();
    session.closed = true;
    out.push_back({false, "$error90-"});
  };
  while (!session.pending.empty() && !session.closed) {
    auto& in = session.pending;
    if (in[0] == '\r' || in[0] == '\n' || (session.optional_hyphen && in[0] == '-')) {
      in.erase(0, 1);
      session.optional_hyphen = false;
      continue;
    }
    session.optional_hyphen = false;
    const Grammar* g = nullptr;
    bool partial = false;
    for (const auto& entry : GrammarTable) {
      std::string t = entry.token;
      if (t.compare(0, in.size(), in) == 0 && in.size() < t.size())
        partial = true;
      if (in.compare(0, t.size(), t) == 0) {
        if (!g || t.size() > std::string(g->token).size())
          g = &entry;
      }
    }
    if (partial && (!g || in.size() == std::string(g->token).size()))
      break;
    if (!g) {
      if (partial)
        break;
      fail();
      break;
    }
    size_t at = std::string(g->token).size();
    std::vector<int> nums;
    bool incomplete = false, bad = false, optional = false;
    for (unsigned i = 0; i < g->fields; ++i) {
      size_t first = at;
      unsigned value = 0;
      while (at < in.size() && in[at] >= '0' && in[at] <= '9') {
        value = value * 10 + unsigned(in[at] - '0');
        ++at;
        if (at - first > 4) {
          bad = true;
          break;
        }
      }
      if (bad)
        break;
      if (first == at) {
        if (at == in.size())
          incomplete = true;
        else
          bad = true;
        break;
      }
      if (at == in.size()) {
        if (g->optional && i + 1 == g->fields && at - first == 3) {
          nums.push_back(int(value));
          optional = true;
          break;
        }
        incomplete = true;
        break;
      }
      if (in[at] != '-') {
        if (g->optional && i + 1 == g->fields && in[at] == '$' && at - first == 3) {
          nums.push_back(int(value));
          break;
        }
        // The old three-field room dialect is recognized only at a new command.
        if (std::string(g->token) == "$psr" && i == 3 && in[at] == '$') {
          bad = true;
          break;
        }
        bad = true;
        break;
      }
      ++at;
      nums.push_back(int(value));
      if (std::string(g->token) == "$psr" && i == 2 && at < in.size() && in[at] == '$') {
        nums.push_back(-1);
        break;
      }
    }
    std::string label;
    if (!bad && !incomplete && g->named) {
      int n = nameEnd(in, at, unsigned(nums.back()));
      if (n == -1)
        incomplete = true;
      else if (n < 0)
        bad = true;
      else {
        label = in.substr(at, size_t(n));
        at += size_t(n);
        if (!name(label))
          bad = true;
      }
    }
    if (bad) {
      fail();
      break;
    }
    if (incomplete)
      break;
    std::string token = g->token;
    bool large =
        token == "$dat" || token == "$rs" || token == "$rr" || token == "$rm" || token == "$rte";
    size_t reserve = large ? snapshotBudget(state_) : 4096;
    if (outputBytes + reserve > MaxReplyBytes) {
      session.closed = true;
      session.pending.clear();
      session.staged.clear();
      out.push_back({false, "$error96-"});
      break;
    }
    in.erase(0, at);
    session.optional_hyphen = optional;
    auto replies = execute(session, token, nums, label);
    for (const auto& r : replies)
      outputBytes += r.payload.size() + 4;
    out.insert(out.end(), replies.begin(), replies.end());
  }
  return out;
}
bool Engine::resolve(uint8_t id, uint8_t f, uint8_t v, RadioCommand& cmd) const {
  if (id >= state_.shades.size() || !feature(f) || (f == 10 && v != 7) || (f == 12 && v != 0) ||
      (f == 1 && v != 0))
    return false;
  const auto& s = state_.shades[id];
  const auto& r = state_.rooms[s.room];
  if (!(s.enabled_features & (1u << f)) || !productFeature(r.product, f))
    return false;
  cmd = {id,
         s.room,
         r.rf_id,
         uint8_t(1u << (s.slot - 1)),
         f,
         uint8_t(f == 12 ? 1 : v),
         uint8_t(f == 1 ? 3 : 1)};
  return true;
}
std::vector<RadioCommand> Engine::scene_commands(uint8_t id, bool& ok) const {
  std::vector<RadioCommand> out;
  ok = false;
  if (id >= state_.scenes.size())
    return out;
  const auto& sc = state_.scenes[id];
  for (auto shade : sc.shades)
    for (const auto& p : sc.positions)
      if (state_.shades[shade].room == p.room) {
        RadioCommand c;
        if (!resolve(shade, p.feature, p.value, c) || out.size() == MaxBatch)
          return {};
        out.push_back(c);
      }
  ok = !out.empty();
  return out;
}
std::vector<Record> Engine::submit(std::vector<RadioCommand> commands) {
  if (busy_)
    return err(93);
  if (commands.empty() || commands.size() > MaxBatch)
    return err(92);
  // Persist requested state before acceptance. On failure it remains a request,
  // not a claim that the radio transmitted. Never automatically replay it.
  auto next = state_;
  for (const auto& c : commands)
    if (control(c.feature))
      setPosition(next.shades[c.shade], c.feature, c.value);
  if (!commit(std::move(next)))
    return err(94);
  if (!hooks_.submit || !hooks_.submit(commands))
    return err(95);
  active_ = std::move(commands);
  busy_ = true;
  std::vector<Record> out = {{true, "$act01-00-"}};
  for (const auto& c : active_)
    out.push_back({true, cp(c.shade, c.feature, c.value)});
  return out;
}
std::vector<Record> Engine::complete(bool success) {
  if (!busy_)
    return {};
  std::vector<Record> out;
  if (!success)
    out.push_back({true, "$error95-"});
  std::set<uint8_t> rooms;
  for (const auto& c : active_)
    rooms.insert(c.room);
  for (auto r : rooms)
    out.push_back({true, "$act02-" + dec(r) + "-"});
  out.push_back({true, "$act00-00-"});
  active_.clear();
  busy_ = false;
  return out;
}
std::vector<Record> Engine::execute(Session& session, const std::string& op,
                                    const std::vector<int>& n, const std::string& label) {
  if (!valid_)
    return err(94);
  if (op == "$dmy")
    return {{false, "$ack"}};
  if (op == "$dat")
    return snapshot();
  if (op == "$RepTst" || op == "$BdgBtl")
    return err(91);  // RF/bootloader semantics not established.
  if (op == "$stps") {
    session.staged.clear();
    if (!busy_)
      return {{false, "$act00-00-"}};
    if (active_.size() != 1 || active_[0].feature != 1)
      return err(93);
    if (hooks_.cancel)
      hooks_.cancel();
    return {};  // Owner reports finite completion.
  }
  if (busy_)
    return err(93);
  auto within = [&](size_t i, int max) { return i < n.size() && n[i] >= 0 && n[i] <= max; };
  if (op == "$rls") {
    if (session.staged.empty())
      return err(92);
    auto batch = std::move(session.staged);
    session.staged.clear();
    if (session.staged_generation != state_.generation)
      return err(92);
    return submit(std::move(batch));
  }
  if (op == "$pss" || op == "$psr" || op == "$rsc") {
    if (!within(0, 99))
      return err(92);
    unsigned f = op == "$rsc" ? 1 : within(1, 31) ? unsigned(n[1]) : 32;
    unsigned value = op == "$rsc" ? 0 : within(2, 255) ? unsigned(n[2]) : 256;
    if (f > 31 || value > 255 || !feature(f))
      return err(91);
    if (op == "$psr" && (n.size() != 4 || !(n[3] == 0 || n[3] == -1)))
      return err();
    std::vector<uint8_t> ids;
    if (op == "$psr") {
      if (size_t(n[0]) >= state_.rooms.size())
        return err(92);
      for (const auto& s : state_.shades)
        if (s.room == n[0])
          ids.push_back(s.id);
    } else
      ids.push_back(uint8_t(n[0]));
    std::vector<RadioCommand> commands;
    for (auto id : ids) {
      RadioCommand cmd;
      if (!resolve(id, uint8_t(f), uint8_t(value), cmd))
        return err(92);
      commands.push_back(cmd);
    }
    if (commands.empty())
      return err(92);
    if (op == "$rsc" || (op == "$psr" && n[3] == 0))
      return submit(std::move(commands));
    if (session.staged.empty())
      session.staged_generation = state_.generation;
    if (session.staged_generation != state_.generation) {
      session.staged.clear();
      return err(92);
    }
    if ((f == 12 && !session.staged.empty()) ||
        (!session.staged.empty() && session.staged[0].feature == 12))
      return err(93);
    auto staged = session.staged;
    for (const auto& cmd : commands) {
      auto it = std::find_if(staged.begin(), staged.end(), [&](const RadioCommand& c) {
        return c.shade == cmd.shade && c.feature == cmd.feature;
      });
      if (it != staged.end())
        *it = cmd;
      else if (staged.size() < MaxBatch)
        staged.push_back(cmd);
      else
        return err(96);
    }
    session.staged = std::move(staged);
    std::vector<Record> out = {{false, "$act01-00-"}};
    for (const auto& c : commands)
      out.push_back({false, cp(c.shade, c.feature, c.value)});
    out.push_back({false, "$done"});
    return out;
  }
  if (op == "$inm") {
    if (!within(0, 99))
      return err(92);
    bool ok = false;
    auto commands = scene_commands(uint8_t(n[0]), ok);
    return ok ? submit(std::move(commands)) : err(92);
  }
  State next = state_;
  bool snapshotAfter = false;
  std::vector<Record> out;
  bool structural = false;
  if (op == "$sdt") {
    if (n.size() != 4 || !date(n[3], n[0], n[1], n[2]))
      return err(97);
    next.clock.year = uint16_t(n[3]);
    next.clock.month = uint8_t(n[0]);
    next.clock.day = uint8_t(n[1]);
    next.clock.weekday = uint8_t(n[2]);
    next.clock.date_valid = true;
    out = {{false, "$done"}};
  } else if (op == "$stm") {
    if (!within(0, 23) || !within(1, 59) || !within(2, 59))
      return err(97);
    next.clock.hour = uint8_t(n[0]);
    next.clock.minute = uint8_t(n[1]);
    next.clock.second = uint8_t(n[2]);
    next.clock.time_valid = true;
    out = {{false, "$done"}};
  } else if (op == "$chksy") {
    if (!within(0, 9999) || n[0] < 2000)
      return err(97);
    return {{false, "$chksy01-"}};
  } else if (op == "$LEDl") {
    if (!within(0, 255))
      return err();
    next.led = uint8_t(n[0]);
  } else if (op == "$ar") {
    if (!within(0, 99) || !product(n[0]))
      return err(92);
    if (next.rooms.size() == MaxRooms)
      return err(7);
    uint16_t rf = 0;
    for (unsigned attempt = 0; attempt < 128; ++attempt) {
      rf = hooks_.random16 ? hooks_.random16() : 0;
      if (rf && std::none_of(next.rooms.begin(), next.rooms.end(),
                             [rf](const Room& r) { return r.rf_id == rf; }))
        break;
      rf = 0;
    }
    if (!rf)
      return err(94);
    Room r{uint8_t(next.rooms.size()), uint8_t(n[0]), rf, label};
    next.rooms.push_back(r);
    out = {{false, roomRecord(r)}};
    structural = true;
  } else if (op == "$as") {
    if (!within(0, 99) || size_t(n[0]) >= next.rooms.size())
      return err(92);
    if (next.shades.size() == MaxShades)
      return err(2);
    unsigned slot = freeSlot(next, n[0]);
    if (!slot)
      return err(3);
    Shade s;
    s.id = uint8_t(next.shades.size());
    s.room = uint8_t(n[0]);
    s.slot = uint8_t(slot);
    s.name = label;
    s.requested.push_back({4, 0});
    next.shades.push_back(s);
    out = {{false, shadeRecord(s)}};
    structural = true;
  } else if (op == "$mer") {
    if (!within(0, 99) || size_t(n[0]) >= next.rooms.size() || !within(1, 99) || !product(n[1]))
      return err(92);
    auto& r = next.rooms[n[0]];
    if (r.product != n[1]) {
      for (auto& s : next.shades)
        if (s.room == r.id)
          s.enabled_features = 0;
      for (auto& sc : next.scenes)
        sc.positions.erase(std::remove_if(sc.positions.begin(), sc.positions.end(),
                                          [&](const ScenePosition& p) {
                                            return p.room == r.id &&
                                                   !productFeature(n[1], p.feature);
                                          }),
                           sc.positions.end());
    }
    r.product = uint8_t(n[1]);
    r.name = label;
    structural = true;
  } else if (op == "$mes") {
    if (!within(0, 99) || size_t(n[0]) >= next.shades.size() || !within(1, 99) ||
        size_t(n[1]) >= next.rooms.size())
      return err(92);
    auto& s = next.shades[n[0]];
    if (s.room != n[1]) {
      unsigned slot = freeSlot(next, n[1]);
      if (!slot)
        return err(3);
      s.room = uint8_t(n[1]);
      s.slot = uint8_t(slot);
      s.enabled_features = 0;
      s.requested.clear();
      s.requested.push_back({4, 0});
      for (auto& sc : next.scenes)
        sc.shades.erase(std::remove(sc.shades.begin(), sc.shades.end(), s.id), sc.shades.end());
    }
    s.name = label;
    structural = true;
  } else if (op == "$rs") {
    if (!within(0, 99) || size_t(n[0]) >= next.shades.size())
      return err(92);
    removeShade(next, n[0]);
    snapshotAfter = true;
    structural = true;
  } else if (op == "$rr") {
    if (!within(0, 99) || size_t(n[0]) >= next.rooms.size())
      return err(92);
    for (size_t i = next.shades.size(); i > 0; --i)
      if (next.shades[i - 1].room == n[0])
        removeShade(next, i - 1);
    next.rooms.erase(next.rooms.begin() + n[0]);
    for (size_t i = 0; i < next.rooms.size(); ++i)
      next.rooms[i].id = uint8_t(i);
    for (auto& s : next.shades)
      if (s.room > n[0])
        --s.room;
    for (auto& sc : next.scenes) {
      sc.positions.erase(std::remove_if(sc.positions.begin(), sc.positions.end(),
                                        [&](const ScenePosition& p) { return p.room == n[0]; }),
                         sc.positions.end());
      for (auto& p : sc.positions)
        if (p.room > n[0])
          --p.room;
    }
    snapshotAfter = true;
    structural = true;
  } else if (op == "$am") {
    if (next.scenes.size() == MaxScenes)
      return err(8);
    Scene s;
    s.id = uint8_t(next.scenes.size());
    s.name = label;
    next.scenes.push_back(s);
    out = {{false, sceneRecord(s)}};
  } else if (op == "$cmn") {
    if (!within(0, 99) || size_t(n[0]) >= next.scenes.size())
      return err(92);
    next.scenes[n[0]].name = label;
  } else if (op == "$rm") {
    if (!within(0, 99) || size_t(n[0]) >= next.scenes.size())
      return err(92);
    removeScene(next, n[0]);
    snapshotAfter = true;
  } else if (op == "$sml") {
    if (!within(0, 99) || size_t(n[0]) >= next.scenes.size() || !within(1, 99) ||
        size_t(n[1]) >= next.shades.size() || !within(2, 1))
      return err(92);
    auto& links = next.scenes[n[0]].shades;
    links.erase(std::remove(links.begin(), links.end(), n[1]), links.end());
    if (n[2])
      links.push_back(uint8_t(n[1]));
    std::sort(links.begin(), links.end());
    out = {{false, "$cq" + dec(n[0]) + "-" + dec(n[1]) + "-" + dec(n[2]) + "-"}};
  } else if (op == "$mrp") {
    if (!within(0, 99) || size_t(n[0]) >= next.scenes.size() || !within(1, 99) ||
        size_t(n[1]) >= next.rooms.size() || !within(2, 31) || !control(n[2]) ||
        !productFeature(next.rooms[n[1]].product, n[2]) || !within(3, 255) || !within(4, 0) ||
        (n[2] == 10 && n[3] != 7))
      return err(92);
    auto& positions = next.scenes[n[0]].positions;
    auto it = std::find_if(positions.begin(), positions.end(), [&](const ScenePosition& p) {
      return p.room == n[1] && p.feature == n[2];
    });
    ScenePosition p{uint8_t(n[1]), uint8_t(n[2]), uint8_t(n[3])};
    if (it == positions.end())
      positions.push_back(p);
    else
      *it = p;
  } else if (op == "$ate" || op == "$mte") {
    size_t offset = op == "$mte" ? 1 : 0;
    if (offset && (!within(0, 99) || size_t(n[0]) >= next.schedules.size()))
      return err(92);
    if (!within(offset, 99) || size_t(n[offset]) >= next.scenes.size() ||
        !within(offset + 1, 255) || !within(offset + 2, 23) || !within(offset + 3, 59))
      return err(92);
    if (!offset && next.schedules.size() == MaxSchedules)
      return err(9);
    Schedule e{uint8_t(offset ? n[0] : next.schedules.size()),
               uint8_t(n[offset]),
               uint8_t(n[offset + 1]),
               uint8_t(n[offset + 2]),
               uint8_t(n[offset + 3]),
               0};
    if (offset) {
      e.last_day = next.schedules[n[0]].last_day;
      next.schedules[n[0]] = e;
    } else {
      next.schedules.push_back(e);
      out = {{false, scheduleRecord(e)}};
    }
  } else if (op == "$rte") {
    if (!within(0, 99) || size_t(n[0]) >= next.schedules.size())
      return err(92);
    next.schedules.erase(next.schedules.begin() + n[0]);
    for (size_t i = 0; i < next.schedules.size(); ++i)
      next.schedules[i].id = uint8_t(i);
    snapshotAfter = true;
  } else
    return err(91);
  if (structural)
    ++next.generation;
  if (!commit(std::move(next)))
    return err(94);
  return snapshotAfter ? snapshot() : out;
}

std::vector<Record> Engine::tick(uint32_t elapsed) {
  auto& c = state_.clock;
  if (!valid_ || !c.date_valid || !c.time_valid || !elapsed)
    return {};
  uint64_t seconds = uint64_t(c.hour) * 3600 + unsigned(c.minute) * 60 + c.second + elapsed;
  uint32_t days = uint32_t(seconds / 86400);
  seconds %= 86400;
  c.hour = uint8_t(seconds / 3600);
  c.minute = uint8_t(seconds / 60 % 60);
  c.second = uint8_t(seconds % 60);
  for (uint32_t d = 0; d < days; ++d) {
    c.weekday = uint8_t(c.weekday % 7 + 1);
    if (++c.day > monthDays(c.year, c.month)) {
      c.day = 1;
      if (++c.month > 12) {
        c.month = 1;
        if (c.year == 9999) {
          c.date_valid = false;
          return err(97);
        }
        ++c.year;
      }
    }
  }
  if (busy_)
    return {};
  uint32_t day = uint32_t(c.year) * 10000 + unsigned(c.month) * 100 + c.day;
  std::vector<RadioCommand> batch;
  State next = state_;
  bool due = false, ok = true;
  for (auto& event : next.schedules)
    if ((event.days & 128) && (event.days & (1u << (c.weekday - 1))) && event.hour == c.hour &&
        event.minute == c.minute && event.last_day < day) {
      due = true;
      event.last_day = day;
      bool sceneOk = false;
      auto commands = scene_commands(event.scene, sceneOk);
      if (!sceneOk || batch.size() + commands.size() > MaxBatch)
        ok = false;
      else
        batch.insert(batch.end(), commands.begin(), commands.end());
    }
  if (!due)
    return {};
  if (!commit(std::move(next)))
    return err(94);
  if (!ok)
    return err(92);
  return submit(std::move(batch));
}
bool validateTransaction(const State& state, const std::string& command) {
  if (command.empty() || command.size() > MaxInput)
    return false;
  uint16_t nextIdentity = 0;
  Hooks hooks;
  hooks.persist = [](const State&) { return true; };
  hooks.submit = [](const std::vector<RadioCommand>&) { return true; };
  hooks.random16 = [&nextIdentity]() { return ++nextIdentity; };
  Engine preview(state, hooks);
  Session session;
  auto replies = preview.feed(session, command);
  if (session.closed || !session.pending.empty() || !session.staged.empty())
    return false;
  return std::none_of(replies.begin(), replies.end(),
                      [](const Record& record) { return record.payload.rfind("$error", 0) == 0; });
}
}  // namespace platinum
