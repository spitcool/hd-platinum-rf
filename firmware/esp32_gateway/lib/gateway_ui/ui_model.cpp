// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include "ui_model.h"

#include <algorithm>
#include <cstdio>
#include <utility>

namespace platinum {
namespace ui {
namespace {
const Shade* shadeWithId(const State& state, uint8_t id) {
  for (const auto& shade : state.shades)
    if (shade.id == id)
      return &shade;
  return nullptr;
}
const Room* roomWithId(const State& state, uint8_t id) {
  for (const auto& room : state.rooms)
    if (room.id == id)
      return &room;
  return nullptr;
}
bool granted(const State& state, const Shade& shade) {
  return roomWithId(state, shade.room) != nullptr && (shade.enabled_features & (1u << 4));
}
bool movedTooFar(int x, int y, int start_x, int start_y) {
  const int64_t dx = int64_t(x) - start_x, dy = int64_t(y) - start_y;
  return dx < -15 || dx > 15 || dy < -15 || dy > 15 || dx * dx + dy * dy > 225;
}
size_t members(const State& state, uint8_t room) {
  size_t count = 0;
  for (const auto& shade : state.shades)
    if (shade.room == room)
      ++count;
  return count;
}
bool roomGranted(const State& state, uint8_t room) {
  if (!roomWithId(state, room))
    return false;
  bool found = false;
  for (const auto& shade : state.shades) {
    if (shade.room != room)
      continue;
    found = true;
    if (!granted(state, shade))
      return false;
  }
  return found;
}
}  // namespace

size_t Model::count(const State& state) const {
  return tab_ == Tab::Shades ? state.shades.size() : state.rooms.size();
}
void Model::sync(const State& state) {
  if (!initialized_) {
    initialized_ = true;
    generation_ = state.generation;
  } else if (generation_ != state.generation) {
    generation_ = state.generation;
    screen_ = Screen::List;
    page_ = 0;
    if (down_)
      cancelTouch();
    feedback("Inventory changed. Select again.");
  }
  if (screen_ == Screen::Detail && ((tab_ == Tab::Shades && !shadeWithId(state, selected_)) ||
                                    (tab_ == Tab::Groups && !roomWithId(state, selected_)))) {
    screen_ = Screen::List;
    if (down_)
      cancelTouch();
    feedback("Target removed. Select again.");
  }
  size_t pages =
      std::max(size_t(1), (count(state) + layout::RowsPerPage - 1) / layout::RowsPerPage);
  if (page_ >= pages) {
    page_ = pages - 1;
    if (down_)
      cancelTouch();
    ++revision_;
  }
}
bool Model::eligible(const State& state) const {
  if (tab_ == Tab::Groups)
    return roomGranted(state, selected_);
  const auto* shade = shadeWithId(state, selected_);
  return shade && granted(state, *shade);
}
bool Model::canControl(const State& state, const Runtime& runtime) const {
  return screen_ == Screen::Detail && runtime.storage_ok && runtime.backend_ready &&
         !runtime.busy && eligible(state);
}
View Model::view(const State& state, const Runtime& runtime) {
  sync(state);
  View result;
  result.screen = screen_;
  result.tab = tab_;
  result.page = page_;
  result.total = count(state);
  result.pages =
      std::max(size_t(1), (result.total + layout::RowsPerPage - 1) / layout::RowsPerPage);
  result.message = message_;
  result.message_error = message_error_;
  result.status = !runtime.storage_ok      ? "Storage fault"
                  : !runtime.backend_ready ? "Radio offline"
                  : runtime.busy           ? "Busy"
                                           : "";
  if (screen_ == Screen::List) {
    result.title = "Platinum";
    for (size_t index = page_ * layout::RowsPerPage;
         index < result.total && result.rows.size() < layout::RowsPerPage; ++index) {
      Row row;
      if (tab_ == Tab::Shades) {
        const auto& shade = state.shades[index];
        row.id = shade.id;
        row.name = shade.name;
        row.count = 1;
        row.enabled = granted(state, shade);
      } else {
        const auto& room = state.rooms[index];
        row.id = room.id;
        row.name = room.name;
        row.count = members(state, room.id);
        row.enabled = roomGranted(state, room.id);
      }
      result.rows.push_back(std::move(row));
    }
    return result;
  }
  result.controls_enabled = canControl(state, runtime);
  if (tab_ == Tab::Shades) {
    const auto* shade = shadeWithId(state, selected_);
    if (shade) {
      result.title = shade->name;
      result.member_count = 1;
    }
  } else {
    const auto* room = roomWithId(state, selected_);
    result.title = room ? room->name : "Unknown room";
    result.member_count = members(state, selected_);
  }
  if (!runtime.storage_ok) {
    result.message = "Storage unavailable";
    result.message_error = true;
  } else if (!runtime.backend_ready) {
    result.message = "Radio unavailable";
    result.message_error = true;
  } else if (runtime.busy) {
    result.message = "Command in progress...";
    result.message_error = false;
  } else if (!eligible(state)) {
    result.message =
        tab_ == Tab::Groups ? "Enable every shade in this group" : "Position control disabled";
    if (result.member_count == 0)
      result.message = "No shades in this group";
    result.message_error = true;
  }
  return result;
}
Model::Hit Model::hit(int x, int y, const State& state, const Runtime& runtime) const {
  if (x < 0 || y < 0 || x >= layout::Width || y >= layout::Height)
    return Hit::None;
  if (screen_ == Screen::Detail) {
    if (layout::Back.contains(x, y))
      return Hit::Back;
    if (canControl(state, runtime)) {
      if (layout::Open.contains(x, y))
        return Hit::Open;
      if (layout::Close.contains(x, y))
        return Hit::Close;
    }
    return Hit::None;
  }
  if (layout::ShadesTab.contains(x, y))
    return Hit::Shades;
  if (layout::GroupsTab.contains(x, y))
    return Hit::Groups;
  for (size_t row = 0; row < layout::RowsPerPage; ++row)
    if (page_ * layout::RowsPerPage + row < count(state) && layout::Rows[row].contains(x, y))
      return static_cast<Hit>(static_cast<unsigned>(Hit::Row0) + row);
  if (page_ > 0 && layout::Previous.contains(x, y))
    return Hit::Previous;
  if ((page_ + 1) * layout::RowsPerPage < count(state) && layout::Next.contains(x, y))
    return Hit::Next;
  return Hit::None;
}
void Model::feedback(std::string message, bool error) {
  if (message_ != message || message_error_ != error) {
    message_ = std::move(message);
    message_error_ = error;
    ++revision_;
  }
}
void Model::cancelTouch() {
  // Retain down_ until the physical finger is released. Otherwise a held finger
  // could become a new press immediately after an inventory/busy transition.
  pressed_ = Hit::None;
  cancelled_ = true;
  wait_for_release_ = true;
}
std::string Model::activate(Hit target, const State& state, const Runtime& runtime) {
  if (target == Hit::Open || target == Hit::Close) {
    if (!canControl(state, runtime))
      return {};
    char command[48];
    unsigned value = target == Hit::Open ? 255 : 0;
    if (tab_ == Tab::Shades)
      std::snprintf(command, sizeof(command), "$pss%02u-04-%03u-$rls", selected_, value);
    else
      std::snprintf(command, sizeof(command), "$psr%u-4-%u-0-", selected_, value);
    feedback("Submitting request...");
    return command;
  }
  if (target == Hit::None)
    return {};
  if (target == Hit::Shades || target == Hit::Groups) {
    Tab desired = target == Hit::Shades ? Tab::Shades : Tab::Groups;
    if (tab_ != desired) {
      tab_ = desired;
      page_ = 0;
    }
  } else if (target == Hit::Previous) {
    if (page_)
      --page_;
  } else if (target == Hit::Next) {
    if ((page_ + 1) * layout::RowsPerPage < count(state))
      ++page_;
  } else if (target == Hit::Back) {
    screen_ = Screen::List;
  } else if (target >= Hit::Row0 && target <= Hit::Row2) {
    size_t index = page_ * layout::RowsPerPage + static_cast<unsigned>(target) -
                   static_cast<unsigned>(Hit::Row0);
    if (index >= count(state))
      return {};
    selected_ = tab_ == Tab::Shades ? state.shades[index].id : state.rooms[index].id;
    screen_ = Screen::Detail;
  }
  feedback("");
  ++revision_;
  return {};
}
std::string Model::touch(bool down, int x, int y, const State& state, const Runtime& runtime) {
  sync(state);
  if (wait_for_release_) {
    if (!down) {
      wait_for_release_ = false;
      down_ = false;
      cancelled_ = false;
    }
    return {};
  }
  if (down) {
    if (!down_) {
      down_ = true;
      cancelled_ = false;
      pressed_ = hit(x, y, state, runtime);
      pressed_x_ = x;
      pressed_y_ = y;
      pressed_revision_ = revision_;
    } else {
      if (movedTooFar(x, y, pressed_x_, pressed_y_) || pressed_revision_ != revision_ ||
          ((pressed_ == Hit::Open || pressed_ == Hit::Close) && !canControl(state, runtime)))
        cancelTouch();
    }
    return {};
  }
  if (!down_)
    return {};
  down_ = false;
  Hit target = pressed_;
  bool accepted = !cancelled_ && pressed_revision_ == revision_ &&
                  !movedTooFar(x, y, pressed_x_, pressed_y_) && target != Hit::None &&
                  hit(x, y, state, runtime) == target;
  pressed_ = Hit::None;
  cancelled_ = false;
  return accepted ? activate(target, state, runtime) : std::string{};
}
}  // namespace ui
}  // namespace platinum
