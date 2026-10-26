// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include <cassert>
#include <climits>
#include <iostream>
#include <string>

#include "ui_model.h"
using namespace platinum;
using namespace platinum::ui;
namespace {
State inventory() {
  State state;
  state.rooms = {{0, 1, 0x1234, "Lounge"}, {1, 1, 0xabcd, "Bedroom"}, {2, 1, 0x4321, "Empty"}};
  state.shades = {{0, 0, 1, "East", 16, {{4, 128}}, {}},
                  {1, 0, 2, "West", 16, {{4, 128}}, {}},
                  {2, 1, 1, "Curtain", 16, {{4, 255}}, {}},
                  {3, 1, 2, "Blackout", 16, {}, {}},
                  {4, 1, 3, "Skylight", 16, {{4, 0}}, {}}};
  assert(Engine::validate(state));
  return state;
}
std::string tap(Model& model, const State& state, const Runtime& runtime, int x, int y) {
  assert(model.touch(true, x, y, state, runtime).empty());
  return model.touch(false, x, y, state, runtime);
}
std::string tap(Model& model, const State& state, const Runtime& runtime, Rect target) {
  return tap(model, state, runtime, target.x + target.width / 2, target.y + target.height / 2);
}
void navigation_and_commands() {
  auto state = inventory();
  Runtime runtime;
  Model model;
  auto view = model.view(state, runtime);
  assert(view.title == "Platinum" && view.status.empty());
  assert(view.rows.size() == 3 && view.page == 0 && view.pages == 2);
  assert(view.rows[0].name == "East" && view.rows[0].count == 1 && view.rows[0].enabled);
  assert(tap(model, state, runtime, layout::Next).empty());
  view = model.view(state, runtime);
  assert(view.rows.size() == 2 && view.page == 1 && view.rows[0].name == "Blackout");
  assert(tap(model, state, runtime, layout::Rows[2]).empty());
  assert(model.view(state, runtime).screen == Screen::List);
  assert(tap(model, state, runtime, layout::Rows[0]).empty());
  view = model.view(state, runtime);
  assert(view.screen == Screen::Detail && view.title == "Blackout" && view.controls_enabled);
  assert(tap(model, state, runtime, layout::Open) == "$pss03-04-255-$rls");
  assert(tap(model, state, runtime, layout::Close) == "$pss03-04-000-$rls");
  assert(model.touch(false, 220, 130, state, runtime).empty());
  assert(tap(model, state, runtime, layout::Back).empty());
  assert(model.view(state, runtime).page == 1);
  assert(tap(model, state, runtime, layout::Previous).empty());
  assert(model.view(state, runtime).page == 0);
  assert(tap(model, state, runtime, layout::Previous).empty());
  assert(model.view(state, runtime).page == 0);
  assert(tap(model, state, runtime, layout::GroupsTab).empty());
  view = model.view(state, runtime);
  assert(view.tab == Tab::Groups && view.rows.size() == 3 && view.rows[0].count == 2);
  assert(tap(model, state, runtime, layout::Rows[0]).empty());
  view = model.view(state, runtime);
  assert(view.member_count == 2 && view.title == "Lounge" && view.controls_enabled);
  assert(tap(model, state, runtime, layout::Open) == "$pss00-04-255-$pss01-04-255-$rls");
  assert(tap(model, state, runtime, layout::Close) == "$pss00-04-000-$pss01-04-000-$rls");
  assert(tap(model, state, runtime, layout::Back).empty());
  assert(tap(model, state, runtime, layout::Rows[1]).empty());
  view = model.view(state, runtime);
  assert(view.member_count == 3 && view.title == "Bedroom" && view.controls_enabled);
  assert(tap(model, state, runtime, layout::Back).empty());
  assert(tap(model, state, runtime, layout::Rows[2]).empty());
  view = model.view(state, runtime);
  assert(!view.controls_enabled && view.member_count == 0 && view.message_error);
  assert(tap(model, state, runtime, layout::Open).empty());
}
void gates_and_groups() {
  auto state = inventory();
  Runtime runtime;
  Model model;
  tap(model, state, runtime, layout::Rows[0]);
  for (unsigned flag = 0; flag < 3; ++flag) {
    Runtime blocked = runtime;
    if (flag == 0)
      blocked.busy = true;
    if (flag == 1)
      blocked.storage_ok = false;
    if (flag == 2)
      blocked.backend_ready = false;
    const auto blocked_view = model.view(state, blocked);
    assert(!blocked_view.controls_enabled);
    assert(blocked_view.status == (flag == 0   ? "Busy"
                                   : flag == 1 ? "Storage fault"
                                               : "Radio offline"));
    assert(tap(model, state, blocked, layout::Open).empty());
    assert(model.touch(true, 70, 130, state, blocked).empty());
    assert(model.touch(false, 70, 130, state, runtime).empty());  // Was disabled at press.
    assert(model.touch(true, 70, 130, state, runtime).empty());
    assert(model.touch(true, 70, 130, state, blocked).empty());
    assert(model.touch(true, 70, 130, state, runtime).empty());
    assert(model.touch(false, 70, 130, state, runtime).empty());  // No rearm after busy clears.
  }
  state.shades[0].enabled_features = 0;
  assert(!model.view(state, runtime).controls_enabled);
  assert(tap(model, state, runtime, layout::Close).empty());
  tap(model, state, runtime, layout::Back);
  tap(model, state, runtime, layout::GroupsTab);
  tap(model, state, runtime, layout::Rows[0]);
  assert(!model.view(state, runtime).controls_enabled);  // Other member remains granted.
  assert(tap(model, state, runtime, layout::Open).empty());
  state.shades[0].enabled_features = 16;
  assert(model.view(state, runtime).controls_enabled);
  assert(model.touch(true, 80, 130, state, runtime).empty());
  state.shades[1].enabled_features = 0;
  assert(
      model.touch(false, 80, 130, state, runtime).empty());  // All members revalidated on release.
}
void touch_safety() {
  auto state = inventory();
  Runtime runtime;
  Model model;
  tap(model, state, runtime, layout::Rows[0]);
  assert(model.touch(true, 60, 130, state, runtime).empty());
  for (int i = 0; i < 100; ++i)
    assert(model.touch(true, 60, 130, state, runtime).empty());
  assert(model.touch(false, 60, 130, state, runtime) == "$pss00-04-255-$rls");
  for (int i = 0; i < 100; ++i)
    assert(model.touch(false, 60, 130, state, runtime).empty());
  model.touch(true, 60, 130, state, runtime);
  model.touch(true, 76, 130, state, runtime);
  model.touch(true, 60, 130, state, runtime);
  assert(model.touch(false, 60, 130, state, runtime).empty());  // Moving back never rearms.
  model.touch(true, 60, 130, state, runtime);
  assert(model.touch(false, 75, 130, state, runtime) == "$pss00-04-255-$rls");
  model.touch(true, 60, 130, state, runtime);
  assert(model.touch(false, 76, 130, state, runtime).empty());
  model.touch(true, layout::Open.x, layout::Open.y, state, runtime);
  assert(model.touch(false, layout::Open.x - 1, layout::Open.y, state, runtime).empty());
  assert(tap(model, state, runtime, layout::Open.x + layout::Open.width, 130).empty());
  assert(tap(model, state, runtime, -1, 130).empty());
  assert(tap(model, state, runtime, 320, 240).empty());
  model.touch(true, 60, 130, state, runtime);
  assert(model.touch(false, 220, 130, state, runtime).empty());  // Open -> close is a drag.
  model.cancelTouch();  // A multi-touch first sample before a valid single press.
  model.touch(true, 60, 130, state, runtime);
  assert(model.touch(false, 60, 130, state, runtime).empty());
  assert(tap(model, state, runtime, 60, 130) == "$pss00-04-255-$rls");
  model.touch(true, INT_MIN, INT_MAX, state, runtime);
  model.touch(true, INT_MAX, INT_MIN, state, runtime);
  assert(model.touch(false, INT_MAX, INT_MIN, state, runtime).empty());
  model.touch(true, 60, 130, state, runtime);
  model.feedback("Other operation finished");
  assert(model.touch(false, 60, 130, state, runtime).empty());
}
void stale_selection() {
  auto state = inventory();
  Runtime runtime;
  Model model;
  tap(model, state, runtime, layout::Rows[0]);
  model.touch(true, 60, 130, state, runtime);
  // Numeric ID now names another physical target after compacting inventory.
  state.shades.erase(state.shades.begin());
  for (size_t i = 0; i < state.shades.size(); ++i)
    state.shades[i].id = uint8_t(i);
  ++state.generation;
  assert(model.touch(false, 60, 130, state, runtime).empty());
  auto view = model.view(state, runtime);
  assert(view.screen == Screen::List && view.message == "Inventory changed. Select again.");
  tap(model, state, runtime, layout::Rows[0]);
  assert(model.view(state, runtime).title == "West");
  assert(tap(model, state, runtime, layout::Close) == "$pss00-04-000-$rls");
  // An inventory update while no touch exists should not consume the next tap.
  ++state.generation;
  model.view(state, runtime);
  tap(model, state, runtime, layout::Rows[1]);
  assert(model.view(state, runtime).screen == Screen::Detail);
}
void views_and_engine() {
  State empty;
  Runtime runtime;
  Model emptyModel;
  assert(emptyModel.view(empty, runtime).rows.empty());
  assert(tap(emptyModel, empty, runtime, layout::Rows[0]).empty());
  assert(tap(emptyModel, empty, runtime, layout::Next).empty());
  auto state = inventory();
  Model model;
  tap(model, state, runtime, layout::Rows[0]);
  auto first = model.view(state, runtime);
  assert(first == model.view(state, runtime));
  state.shades[0].requested[0].value = 42;
  assert(first != model.view(state, runtime));  // History label changes, not measured position.
  assert(model.view(state, runtime).message == "History (order unknown): 42");
  state.shades[0].last_requested_feature = 4;
  assert(model.view(state, runtime).message == "Last command: raw 42");
  state.shades[0].requested.push_back({18, 63});
  state.shades[0].last_requested_feature = 18;
  assert(model.view(state, runtime).message == "Earlier request: raw 42");
  state.shades[0].requested.pop_back();
  state.shades[0].last_requested_feature = 4;
  state.shades[0].name = "East window";
  assert(first != model.view(state, runtime));
  auto second = model.view(state, runtime);
  runtime.busy = true;
  assert(second != model.view(state, runtime));
  runtime.busy = false;
  assert(model.view(state, runtime).status.empty());
  unsigned writes = 0, submits = 0;
  std::vector<RadioCommand> submitted;
  Engine engine(state, Hooks{[&](const State&) {
                               ++writes;
                               return true;
                             },
                             [&](const std::vector<RadioCommand>& commands) {
                               ++submits;
                               submitted = commands;
                               return true;
                             },
                             {},
                             {}});
  Session session;
  auto command = tap(model, state, runtime, layout::Open);
  assert(validateTransaction(state, command));
  engine.feed(session, command);
  assert(submits == 1 && submitted.size() == 1 && submitted[0].shade == 0 &&
         submitted[0].value == 255);
  engine.complete(true);
  model.feedback("Sent; movement unconfirmed");
  tap(model, state, runtime, layout::Back);
  tap(model, state, runtime, layout::GroupsTab);
  tap(model, state, runtime, layout::Rows[0]);
  command = tap(model, state, runtime, layout::Close);
  assert(validateTransaction(state, command));
  session = {};
  engine.feed(session, command);
  assert(submits == 2 && submitted.size() == 2 && submitted[0].value == 0 &&
         submitted[1].value == 0);
  assert(writes == 2);
}
void feature_controls_and_mapping() {
  auto state = inventory();
  state.rooms[0].product = 2;
  for (auto& shade : state.shades)
    if (shade.room == 0) shade.enabled_features = (1u << 4) | (1u << 18) | (1u << 10);
  Runtime runtime;
  Model model;
  tap(model, state, runtime, layout::Rows[0]);
  auto unknown = model.view(state, runtime);
  assert(unknown.control_label == "Primary" && unknown.first_caption == "Raw 255");
  assert(unknown.second_caption == "Raw 0" && unknown.raw_value == 128);
  assert(tap(model, state, runtime, layout::FeatureNext).empty());
  auto secondary = model.view(state, runtime);
  assert(secondary.feature == 18 && secondary.control_label == "Secondary");
  assert(tap(model, state, runtime, layout::Decrease).empty());
  assert(model.view(state, runtime).raw_value == 127);
  assert(tap(model, state, runtime, layout::Apply) == "$pss00-18-127-$rls");
  assert(tap(model, state, runtime, layout::Increase).empty());
  assert(tap(model, state, runtime, layout::Apply) == "$pss00-18-128-$rls");
  runtime.backend_features = 1u << 4;
  assert(!model.view(state, runtime).controls_enabled);
  assert(tap(model, state, runtime, layout::Apply).empty());
  runtime.backend_features = KnownFeatureMask;
  state.shades[0].controls = {{18, ControlRole::TopRail, EndpointMapping::OpenAtZero}};
  auto mapped = model.view(state, runtime);
  assert(mapped.control_label == "Top rail" && mapped.first_caption == "Open");
  assert(tap(model, state, runtime, layout::Open) == "$pss00-18-000-$rls");
  assert(tap(model, state, runtime, layout::Close) == "$pss00-18-255-$rls");
  tap(model, state, runtime, layout::FeatureNext);
  auto preset = model.view(state, runtime);
  assert(preset.feature == 10 && preset.first_caption == "Preset 7");
  assert(!preset.second_enabled && !preset.raw_controls_enabled);
  assert(tap(model, state, runtime, layout::Open) == "$pss00-10-007-$rls");
  assert(tap(model, state, runtime, layout::Apply).empty());
  assert(tap(model, state, runtime, layout::Close).empty());
  // Heterogeneous explicit directions in one room are staged individually.
  state.shades[0].controls = {{4, ControlRole::TopRail, EndpointMapping::OpenAtZero}};
  state.shades[1].controls = {{4, ControlRole::Lift, EndpointMapping::OpenAt255}};
  tap(model, state, runtime, layout::Back);
  tap(model, state, runtime, layout::GroupsTab);
  tap(model, state, runtime, layout::Rows[0]);
  assert(model.view(state, runtime).first_caption == "Open");
  assert(tap(model, state, runtime, layout::Open) == "$pss00-04-000-$pss01-04-255-$rls");
  state.shades[1].controls.clear();
  assert(model.view(state, runtime).first_caption == "Raw 255");
  assert(tap(model, state, runtime, layout::Open) == "$pss00-04-255-$pss01-04-255-$rls");
  // Tilt features have raw values, never invented open/closed or rail labels.
  state.rooms[0].product = 6;
  state.shades[0].enabled_features = (1u << 4) | (1u << 7) | (1u << 19);
  state.shades[0].controls.clear();
  Model tilt;
  tap(tilt, state, runtime, layout::Rows[0]);
  tap(tilt, state, runtime, layout::FeatureNext);
  assert(tilt.view(state, runtime).feature == 7 && tilt.view(state, runtime).first_caption == "Raw 255");
  assert(tap(tilt, state, runtime, layout::Apply) == "$pss00-07-128-$rls");
  tap(tilt, state, runtime, layout::FeatureNext);
  assert(tilt.view(state, runtime).feature == 19);
  assert(tap(tilt, state, runtime, layout::Apply) == "$pss00-19-128-$rls");
  // Busy latches cancel fine-value actions even if it clears before release.
  tilt.touch(true, 160, 182, state, runtime);
  runtime.busy = true;
  tilt.touch(true, 160, 182, state, runtime);
  runtime.busy = false;
  assert(tilt.touch(false, 160, 182, state, runtime).empty());
}
}  // namespace
int main() {
  navigation_and_commands();
  gates_and_groups();
  touch_safety();
  stale_selection();
  views_and_engine();
  feature_controls_and_mapping();
  std::cout << "Touch UI model checks passed\n";
}
