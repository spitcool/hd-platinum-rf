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
bool granted(const State& state, const Shade& shade, uint32_t backend) {
  for (uint8_t f : {4, 18, 7, 19, 10})
    if (featureAvailable(state, shade, f, backend))
      return true;
  return false;
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
bool roomGranted(const State& state, uint8_t room, uint32_t backend) {
  if (!roomWithId(state, room))
    return false;
  bool found = false;
  for (const auto& shade : state.shades) {
    if (shade.room != room)
      continue;
    found = true;
    if (!granted(state, shade, backend))
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
bool Model::eligible(const State& state, const Runtime& runtime) const {
  if (tab_ == Tab::Groups) {
    bool found = false;
    for (const auto& shade : state.shades) {
      if (shade.room != selected_)
        continue;
      found = true;
      if (!featureAvailable(state, shade, feature_, runtime.backend_features))
        return false;
    }
    return found;
  }
  const auto* shade = shadeWithId(state, selected_);
  return shade && featureAvailable(state, *shade, feature_, runtime.backend_features);
}
std::vector<uint8_t> Model::features(const State& state) const {
  const auto* shade = tab_ == Tab::Shades ? shadeWithId(state, selected_) : nullptr;
  const auto* room = roomWithId(state, shade ? shade->room : selected_);
  std::vector<uint8_t> result;
  if (room)
    for (uint8_t f : {4, 18, 7, 19, 10})
      if (productSupportsFeature(room->product, f))
        result.push_back(f);
  return result;
}
void Model::selectFeature(const State& state, uint8_t f) {
  feature_ = f;
  raw_value_ = f == 10 ? 7 : 128;
  // A group has no single requested position. A shade's initial editor value
  // is its last request, never a measurement or inferred physical position.
  if (tab_ == Tab::Shades) {
    const auto* shade = shadeWithId(state, selected_);
    if (shade)
      for (const auto& p : shade->requested)
        if (p.feature == f)
          raw_value_ = p.value;
  }
}
bool Model::endpointsMapped(const State& state) const {
  bool found = false;
  for (const auto& shade : state.shades) {
    if (tab_ == Tab::Groups ? shade.room != selected_ : shade.id != selected_)
      continue;
    uint8_t value;
    found = true;
    if (!endpointValue(shade, feature_, true, value))
      return false;
  }
  return found;
}
bool Model::canControl(const State& state, const Runtime& runtime) const {
  return screen_ == Screen::Detail && runtime.storage_ok && runtime.backend_ready &&
         !runtime.busy && eligible(state, runtime);
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
        row.enabled = granted(state, shade, runtime.backend_features);
      } else {
        const auto& room = state.rooms[index];
        row.id = room.id;
        row.name = room.name;
        row.count = members(state, room.id);
        row.enabled = roomGranted(state, room.id, runtime.backend_features);
      }
      result.rows.push_back(std::move(row));
    }
    return result;
  }
  result.controls_enabled = canControl(state, runtime);
  result.feature = feature_;
  result.raw_value = raw_value_;
  result.feature_navigation = features(state).size() > 1 && !runtime.busy;
  result.raw_controls_enabled = result.controls_enabled && feature_ != 10;
  result.second_enabled = result.raw_controls_enabled;
  Shade unknown;
  result.control_label = controlLabel(unknown, feature_);
  if (feature_ == 10) {
    result.first_caption = "Preset 7";
    result.second_caption.clear();
  } else if (endpointsMapped(state)) {
    result.first_caption = "Open";
    result.second_caption = "Close";
  }
  if (tab_ == Tab::Shades) {
    const auto* shade = shadeWithId(state, selected_);
    if (shade) {
      result.title = shade->name;
      result.member_count = 1;
      result.control_label = controlLabel(*shade, feature_);
      if (result.message.empty()) {
        result.message = "No request history";
        for (const auto& position : shade->requested)
          if (position.feature == feature_) {
            result.message = isLatestRequestedFeature(*shade, feature_)
                                 ? "Last command: raw "
                             : shade->last_requested_feature ? "Earlier request: raw "
                                                             : "History (order unknown): ";
            result.message += std::to_string(position.value);
            break;
          }
      }
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
  } else if (!eligible(state, runtime)) {
    result.message =
        tab_ == Tab::Groups ? "Feature unavailable for this group" : "Feature unavailable";
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
    if (!runtime.busy && features(state).size() > 1) {
      if (layout::FeaturePrevious.contains(x, y)) return Hit::FeaturePrevious;
      if (layout::FeatureNext.contains(x, y)) return Hit::FeatureNext;
    }
    if (canControl(state, runtime)) {
      if (layout::Open.contains(x, y))
        return Hit::Open;
      if (feature_ != 10 && layout::Close.contains(x, y))
        return Hit::Close;
      if (feature_ != 10) {
        if (layout::Decrease.contains(x, y) && raw_value_ > 0) return Hit::Decrease;
        if (layout::Increase.contains(x, y) && raw_value_ < 255) return Hit::Increase;
        if (layout::Apply.contains(x, y)) return Hit::Apply;
      }
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
  if (target == Hit::FeaturePrevious || target == Hit::FeatureNext) {
    if (runtime.busy) return {};
    const auto available = features(state);
    auto it = std::find(available.begin(), available.end(), feature_);
    if (it == available.end() || available.empty()) return {};
    size_t index = size_t(it - available.begin());
    index = (index + (target == Hit::FeatureNext ? 1 : available.size() - 1)) % available.size();
    selectFeature(state, available[index]);
    feedback("");
    ++revision_;
    return {};
  }
  if (target == Hit::Decrease || target == Hit::Increase) {
    if (!canControl(state, runtime) || feature_ == 10) return {};
    if (target == Hit::Decrease && raw_value_ > 0) --raw_value_;
    if (target == Hit::Increase && raw_value_ < 255) ++raw_value_;
    feedback("");
    ++revision_;
    return {};
  }
  if (target == Hit::Open || target == Hit::Close || target == Hit::Apply) {
    if (!canControl(state, runtime))
      return {};
    const bool group = tab_ == Tab::Groups;
    std::string command;
    if (feature_ == 10)
      command = rawControlTransaction(state, selected_, group, feature_, 7, runtime.backend_features);
    else if (target != Hit::Apply && endpointsMapped(state))
      command = endpointTransaction(state, selected_, group, feature_, target == Hit::Open,
                                    runtime.backend_features);
    else
      command = rawControlTransaction(state, selected_, group, feature_,
                                       target == Hit::Apply ? raw_value_ : target == Hit::Open ? 255 : 0,
                                       runtime.backend_features);
    if (command.empty()) return {};
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
    selectFeature(state, 4);
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
          ((pressed_ == Hit::Open || pressed_ == Hit::Close || pressed_ == Hit::Apply ||
            pressed_ == Hit::Decrease || pressed_ == Hit::Increase) && !canControl(state, runtime)) ||
          ((pressed_ == Hit::FeaturePrevious || pressed_ == Hit::FeatureNext) && runtime.busy))
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
