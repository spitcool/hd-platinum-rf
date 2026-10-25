// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <cstdint>
#include <functional>
#include <string>
#include <vector>

namespace platinum {
constexpr size_t MaxRooms = 32, MaxShades = 100, MaxScenes = 32, MaxSchedules = 64;
constexpr size_t MaxInput = 1024, MaxBatch = 100;
constexpr size_t MaxSnapshotBytes = 49152, MaxReplyBytes = 65536;
struct Room {
  uint8_t id = 0, product = 0;
  uint16_t rf_id = 0;
  std::string name;
};
struct Position {
  uint8_t feature = 4, value = 0;
};
struct Shade {
  uint8_t id = 0, room = 0, slot = 1;
  std::string name;
  uint32_t enabled_features = 0;    // Explicit installation grants; bit index = feature.
  std::vector<Position> requested;  // Never a measurement of physical position.
};
struct ScenePosition {
  uint8_t room = 0, feature = 4, value = 0;
};
struct Scene {
  uint8_t id = 0;
  std::string name;
  std::vector<uint8_t> shades;
  std::vector<ScenePosition> positions;
};
struct Schedule {
  uint8_t id = 0, scene = 0, days = 0, hour = 0, minute = 0;
  uint32_t last_day = 0;
};
struct Clock {
  uint16_t year = 0;
  uint8_t month = 0, day = 0, weekday = 0, hour = 0, minute = 0, second = 0;
  bool date_valid = false, time_valid = false;
};
struct State {
  uint32_t schema = 1, generation = 0;
  uint8_t led = 0;
  std::string title = "Platinum", mac = "000000000000";
  std::vector<Room> rooms;
  std::vector<Shade> shades;
  std::vector<Scene> scenes;
  std::vector<Schedule> schedules;
  Clock clock;
};
struct RadioCommand {
  uint8_t shade = 0, room = 0;
  uint16_t rf_id = 0;
  uint8_t mask = 0, feature = 4, value = 0, flags = 1;
};
struct Record {
  bool broadcast = false;
  std::string payload;
};
struct Session {
  std::string pending;
  std::vector<RadioCommand> staged;
  uint32_t staged_generation = 0;
  bool optional_hyphen = false, closed = false;
};
struct Hooks {
  std::function<bool(const State&)> persist;
  // Called with a validated bounded batch. Return false without acceptance,
  // true only if ownership was taken. Invoke complete() after finite RF work.
  std::function<bool(const std::vector<RadioCommand>&)> submit;
  std::function<uint16_t()> random16;
  std::function<void()> cancel;  // Abort owned finite work; cannot undo emitted RF.
};
// Versioned bounded binary encoding with CRC32; decode validates all references.
std::string encodeState(const State& state);
bool decodeState(const std::string& bytes, State& state);
// Validate one complete HTTP command transaction without persistence or RF I/O.
// Staged commands must include release; unknown/error/incomplete requests fail.
bool validateTransaction(const State& state, const std::string& command);
class Engine {
 public:
  explicit Engine(State initial = {}, Hooks hooks = {});
  const State& state() const {
    return state_;
  }
  bool valid() const {
    return valid_;
  }
  bool busy() const {
    return busy_;
  }
  static bool validate(const State& state);
  std::vector<Record> feed(Session&, const std::string& bytes);
  std::vector<Record> snapshot() const;
  // Completion means submitted RF or simulation, never physical confirmation.
  std::vector<Record> complete(bool success);
  // Advance monotonic elapsed seconds. Wall clock only starts after sdt + stm.
  // Missed events are not replayed; each due event is burned durably before RF.
  std::vector<Record> tick(uint32_t elapsed_seconds);
  // Installation provisioning path; validates and commits a replacement state.
  // Refused while work is active. Configuration must not reset sequence NVS.
  bool replace(State state);

 private:
  State state_;
  Hooks hooks_;
  bool valid_ = true, busy_ = false;
  std::vector<RadioCommand> active_;
  bool commit(State candidate);
  std::vector<Record> execute(Session&, const std::string&, const std::vector<int>&,
                              const std::string&);
  std::vector<Record> submit(std::vector<RadioCommand> commands);
  bool resolve(uint8_t shade, uint8_t feature, uint8_t value, RadioCommand&) const;
  std::vector<RadioCommand> scene_commands(uint8_t id, bool& ok) const;
};
}  // namespace platinum
