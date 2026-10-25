// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

#include <cstddef>
#include <cstdint>
#include <string>
#include <tuple>
#include <vector>

#include "gateway_core.h"

namespace platinum {
namespace ui {
struct Rect {
  int x, y, width, height;
  constexpr bool contains(int px, int py) const {
    return px >= x && py >= y && px < x + width && py < y + height;
  }
};
namespace layout {
constexpr int Width = 320, Height = 240;
constexpr size_t RowsPerPage = 3;
constexpr Rect ShadesTab{8, 32, 148, 30};
constexpr Rect GroupsTab{164, 32, 148, 30};
constexpr Rect Rows[RowsPerPage] = {{8, 70, 304, 42}, {8, 114, 304, 42}, {8, 158, 304, 42}};
constexpr Rect Previous{8, 206, 64, 28};
constexpr Rect Next{248, 206, 64, 28};
constexpr Rect Back{8, 4, 62, 28};
constexpr Rect Open{12, 100, 142, 100};
constexpr Rect Close{166, 100, 142, 100};
}  // namespace layout

enum class Tab : uint8_t { Shades, Groups };
enum class Screen : uint8_t { List, Detail };
struct Runtime {
  bool busy = false;
  bool storage_ok = true;
  bool backend_ready = true;
};
struct Row {
  uint8_t id = 0;
  std::string name;
  size_t count = 0;
  bool enabled = false;
  bool operator==(const Row& rhs) const {
    return std::tie(id, name, count, enabled) == std::tie(rhs.id, rhs.name, rhs.count, rhs.enabled);
  }
  bool operator!=(const Row& rhs) const {
    return !(*this == rhs);
  }
};
struct View {
  Screen screen = Screen::List;
  Tab tab = Tab::Shades;
  size_t page = 0, pages = 1, total = 0;
  std::vector<Row> rows;
  std::string title, message, status;
  size_t member_count = 0;
  bool controls_enabled = false;
  bool message_error = false;
  bool operator==(const View& rhs) const {
    return std::tie(screen, tab, page, pages, total, rows, title, message, status, member_count,
                    controls_enabled, message_error) ==
           std::tie(rhs.screen, rhs.tab, rhs.page, rhs.pages, rhs.total, rhs.rows, rhs.title,
                    rhs.message, rhs.status, rhs.member_count, rhs.controls_enabled,
                    rhs.message_error);
  }
  bool operator!=(const View& rhs) const {
    return !(*this == rhs);
  }
};

// No display, touch driver, network, persistence or radio I/O. Caller supplies
// state and live gates on every sample and dispatches any returned command
// through the ordinary Engine. Room groups use existing inventory membership.
class Model {
 public:
  View view(const State& state, const Runtime& runtime);
  // Sample one finger only. On release pass its last known coordinates.
  // Multi-touch, wake-up gestures and device errors should call cancelTouch().
  // Commands emit once on a stationary release inside the original hitbox.
  std::string touch(bool down, int x, int y, const State& state, const Runtime& runtime);
  void cancelTouch();
  void feedback(std::string message, bool error = false);
  uint32_t revision() const {
    return revision_;
  }

 private:
  enum class Hit : uint8_t {
    None,
    Shades,
    Groups,
    Previous,
    Next,
    Row0,
    Row1,
    Row2,
    Back,
    Open,
    Close
  };
  void sync(const State& state);
  Hit hit(int x, int y, const State& state, const Runtime& runtime) const;
  bool eligible(const State& state) const;
  bool canControl(const State& state, const Runtime& runtime) const;
  size_t count(const State& state) const;
  std::string activate(Hit target, const State& state, const Runtime& runtime);
  Tab tab_ = Tab::Shades;
  Screen screen_ = Screen::List;
  size_t page_ = 0;
  uint8_t selected_ = 0;
  uint32_t generation_ = 0, revision_ = 0, pressed_revision_ = 0;
  bool initialized_ = false, down_ = false, cancelled_ = false, wait_for_release_ = false;
  int pressed_x_ = 0, pressed_y_ = 0;
  Hit pressed_ = Hit::None;
  std::string message_;
  bool message_error_ = false;
};
}  // namespace ui
}  // namespace platinum
