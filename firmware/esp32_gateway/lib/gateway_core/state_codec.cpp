// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include <utility>

#include "gateway_core.h"
namespace platinum {
namespace {
constexpr size_t MaxStateBytes = 65536;
uint32_t crc(const std::string& s, size_t end) {
  uint32_t c = 0xffffffff;
  for (size_t i = 0; i < end; ++i) {
    c ^= uint8_t(s[i]);
    for (unsigned b = 0; b < 8; ++b)
      c = (c >> 1) ^ ((c & 1) ? 0xedb88320u : 0u);
  }
  return ~c;
}
struct Writer {
  std::string data = "PGW1";
  void u8(unsigned n) {
    data.push_back(char(n));
  }
  void u16(unsigned n) {
    u8(n);
    u8(n >> 8);
  }
  void u32(uint32_t n) {
    u16(n);
    u16(n >> 16);
  }
  void text(const std::string& s) {
    u16(s.size());
    data += s;
  }
};
struct Reader {
  const std::string& data;
  size_t at = 4;
  bool ok = true;
  unsigned u8() {
    if (at >= data.size() - 4) {
      ok = false;
      return 0;
    }
    return uint8_t(data[at++]);
  }
  unsigned u16() {
    unsigned lo = u8();
    return lo | (u8() << 8);
  }
  uint32_t u32() {
    uint32_t lo = u16();
    return lo | (uint32_t(u16()) << 16);
  }
  size_t count(size_t max) {
    size_t n = u16();
    if (n > max) {
      ok = false;
      return 0;
    }
    return n;
  }
  std::string text() {
    size_t n = count(100);
    if (!ok || at + n > data.size() - 4) {
      ok = false;
      return {};
    }
    auto s = data.substr(at, n);
    at += n;
    return s;
  }
};
}  // namespace
std::string encodeState(const State& s) {
  if (!Engine::validate(s))
    return {};
  Writer w;
  w.u32(s.schema);
  w.u32(s.generation);
  w.u8(s.led);
  w.text(s.title);
  w.text(s.mac);
  const auto& c = s.clock;
  w.u16(c.year);
  w.u8(c.month);
  w.u8(c.day);
  w.u8(c.weekday);
  w.u8(c.hour);
  w.u8(c.minute);
  w.u8(c.second);
  w.u8(c.date_valid);
  w.u8(c.time_valid);
  w.u16(s.rooms.size());
  for (const auto& r : s.rooms) {
    w.u8(r.id);
    w.u8(r.product);
    w.u16(r.rf_id);
    w.text(r.name);
  }
  w.u16(s.shades.size());
  for (const auto& sh : s.shades) {
    w.u8(sh.id);
    w.u8(sh.room);
    w.u8(sh.slot);
    w.text(sh.name);
    w.u32(sh.enabled_features);
    w.u16(sh.requested.size());
    for (const auto& p : sh.requested) {
      w.u8(p.feature);
      w.u8(p.value);
    }
  }
  w.u16(s.scenes.size());
  for (const auto& sc : s.scenes) {
    w.u8(sc.id);
    w.text(sc.name);
    w.u16(sc.shades.size());
    for (auto id : sc.shades)
      w.u8(id);
    w.u16(sc.positions.size());
    for (const auto& p : sc.positions) {
      w.u8(p.room);
      w.u8(p.feature);
      w.u8(p.value);
    }
  }
  w.u16(s.schedules.size());
  for (const auto& e : s.schedules) {
    w.u8(e.id);
    w.u8(e.scene);
    w.u8(e.days);
    w.u8(e.hour);
    w.u8(e.minute);
    w.u32(e.last_day);
  }
  w.u32(crc(w.data, w.data.size()));
  return w.data.size() <= MaxStateBytes ? w.data : std::string{};
}
bool decodeState(const std::string& bytes, State& output) {
  if (bytes.size() < 12 || bytes.size() > MaxStateBytes || bytes.compare(0, 4, "PGW1"))
    return false;
  uint32_t checksum = 0;
  for (unsigned i = 0; i < 4; ++i)
    checksum |= uint32_t(uint8_t(bytes[bytes.size() - 4 + i])) << (i * 8);
  if (checksum != crc(bytes, bytes.size() - 4))
    return false;
  Reader r{bytes};
  State s;
  s.schema = r.u32();
  s.generation = r.u32();
  s.led = uint8_t(r.u8());
  s.title = r.text();
  s.mac = r.text();
  auto& c = s.clock;
  c.year = uint16_t(r.u16());
  c.month = uint8_t(r.u8());
  c.day = uint8_t(r.u8());
  c.weekday = uint8_t(r.u8());
  c.hour = uint8_t(r.u8());
  c.minute = uint8_t(r.u8());
  c.second = uint8_t(r.u8());
  unsigned dv = r.u8(), tv = r.u8();
  if (dv > 1 || tv > 1)
    return false;
  c.date_valid = dv;
  c.time_valid = tv;
  size_t count = r.count(MaxRooms);
  for (size_t i = 0; i < count && r.ok; ++i) {
    Room room;
    room.id = uint8_t(r.u8());
    room.product = uint8_t(r.u8());
    room.rf_id = uint16_t(r.u16());
    room.name = r.text();
    s.rooms.push_back(std::move(room));
  }
  count = r.count(MaxShades);
  for (size_t i = 0; i < count && r.ok; ++i) {
    Shade sh;
    sh.id = uint8_t(r.u8());
    sh.room = uint8_t(r.u8());
    sh.slot = uint8_t(r.u8());
    sh.name = r.text();
    sh.enabled_features = r.u32();
    size_t positions = r.count(5);
    for (size_t j = 0; j < positions && r.ok; ++j) {
      Position p;
      p.feature = uint8_t(r.u8());
      p.value = uint8_t(r.u8());
      sh.requested.push_back(p);
    }
    s.shades.push_back(std::move(sh));
  }
  count = r.count(MaxScenes);
  for (size_t i = 0; i < count && r.ok; ++i) {
    Scene sc;
    sc.id = uint8_t(r.u8());
    sc.name = r.text();
    size_t links = r.count(MaxShades);
    for (size_t j = 0; j < links && r.ok; ++j)
      sc.shades.push_back(uint8_t(r.u8()));
    size_t positions = r.count(MaxRooms * 5);
    for (size_t j = 0; j < positions && r.ok; ++j) {
      ScenePosition p;
      p.room = uint8_t(r.u8());
      p.feature = uint8_t(r.u8());
      p.value = uint8_t(r.u8());
      sc.positions.push_back(p);
    }
    s.scenes.push_back(std::move(sc));
  }
  count = r.count(MaxSchedules);
  for (size_t i = 0; i < count && r.ok; ++i) {
    Schedule e;
    e.id = uint8_t(r.u8());
    e.scene = uint8_t(r.u8());
    e.days = uint8_t(r.u8());
    e.hour = uint8_t(r.u8());
    e.minute = uint8_t(r.u8());
    e.last_day = r.u32();
    s.schedules.push_back(e);
  }
  if (!r.ok || r.at != bytes.size() - 4 || !Engine::validate(s))
    return false;
  output = std::move(s);
  return true;
}
}  // namespace platinum
