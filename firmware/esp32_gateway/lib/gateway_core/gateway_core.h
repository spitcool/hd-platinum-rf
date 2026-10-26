// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once
#include <cstdint>
#include <functional>
#include <optional>
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
// Installation facts only. Room product metadata and feature grants never
// populate these fields. Unknown direction must be presented as a raw value.
enum class ControlRole : uint8_t { Unknown, Lift, TopRail, BottomRail };
enum class EndpointMapping : uint8_t { Unknown, OpenAtZero, OpenAt255 };
struct ControlMapping {
  uint8_t feature = 4;  // Physical travel mapping is supported for 4 and 18 only.
  ControlRole role = ControlRole::Unknown;
  EndpointMapping endpoints = EndpointMapping::Unknown;
};
struct Shade {
  uint8_t id = 0, room = 0, slot = 1;
  std::string name;
  uint32_t enabled_features = 0;    // Explicit installation grants; bit index = feature.
  std::vector<Position> requested;  // Per-feature request history, never measured position.
  std::vector<ControlMapping> controls;  // At most one entry each for features 4 and 18.
  // Most recently requested control. Unknown after ambiguous legacy migration;
  // vector insertion order is not chronology. This does not confirm delivery.
  std::optional<uint8_t> last_requested_feature = std::nullopt;
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
  uint32_t schema = 3, generation = 0;
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
constexpr uint32_t KnownFeatureMask =
    (1u << 1) | (1u << 4) | (1u << 7) | (1u << 10) | (1u << 12) | (1u << 18) | (1u << 19);
// Product support is the observed app contract, not installed rail geometry,
// authorization, RF implementation support, or physical qualification.
bool productSupportsFeature(uint8_t product, uint8_t feature);
uint32_t productFeatureMask(uint8_t product);
ControlMapping controlMapping(const Shade& shade, uint8_t feature);
std::string controlLabel(const Shade& shade, uint8_t feature);
bool endpointValue(const Shade& shade, uint8_t feature, bool open, uint8_t& value);
bool featureAvailable(const State& state, const Shade& shade, uint8_t feature,
                      uint32_t backend_features = KnownFeatureMask);
// Null when chronology is unknown; otherwise refers into shade.requested.
const Position* lastRequestedPosition(const Shade& shade);
bool isLatestRequestedFeature(const Shade& shade, uint8_t feature);
// Use when the physical binding is replaced; rename alone preserves history.
void clearRequestedHistory(Shade& shade);
// Empty means invalid/unavailable; no side effects. Room endpoint transactions
// validate every member, stage each member's own mapped value, then release once.
std::string rawControlTransaction(const State& state, uint8_t target, bool room,
                                  uint8_t feature, uint8_t value,
                                  uint32_t backend_features = KnownFeatureMask);
std::string endpointTransaction(const State& state, uint8_t target, bool room,
                                uint8_t feature, bool open,
                                uint32_t backend_features = KnownFeatureMask);
// Versioned bounded binary encoding with CRC32; decode validates all references.
// Schemas 1/2 upgrade to 3. Schema 1 has unknown control mappings. Legacy latest
// is inferred only for exactly one history entry; multiple entries stay unknown.
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
