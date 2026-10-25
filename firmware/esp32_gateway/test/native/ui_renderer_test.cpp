// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include "ui_renderer.h"

#include <cassert>
#include <iostream>
#include <vector>

using namespace platinum::ui;
namespace {
struct Text {
  int x, y;
  std::string value;
  Font font;
  uint32_t color;
};
struct Paint {
  Rect rect;
  uint32_t color;
};
struct Recorder final : Canvas {
  std::vector<Text> labels;
  std::vector<Paint> paints;
  int textWidth(const std::string& s, Font font) override {
    int count = 0;
    for (unsigned char ch : s)
      if ((ch & 0xc0) != 0x80)
        ++count;
    return count * (font == Font::Small ? 7 : font == Font::Body ? 8 : 11);
  }
  void rectangle(const Rect& rect, uint32_t color, int radius = 0) override {
    assert(rect.x >= 0 && rect.y >= 0 && rect.width >= 0 && rect.height >= 0);
    assert(rect.x + rect.width <= 320 && rect.y + rect.height <= 240);
    assert(radius >= 0 && radius * 2 <= rect.width && radius * 2 <= rect.height);
    paints.push_back({rect, color});
  }
  void text(int x, int y, const std::string& value, Font font, uint32_t color) override {
    assert(x >= 0 && y >= 0 && x + textWidth(value, font) <= 320);
    assert(y + (font == Font::Small ? 15 : font == Font::Body ? 16 : 22) <= 240);
    labels.push_back({x, y, value, font, color});
  }
  const Text& find(const std::string& text) const {
    for (const auto& label : labels)
      if (label.value == text)
        return label;
    assert(false);
    return labels.front();
  }
};
View sample() {
  View v;
  v.total = 4;
  v.pages = 2;
  v.rows = {{0, "East window", 1, true},
            {1, "A very long shade name \xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9", 1, true},
            {2, "Bedroom", 1, false}};
  return v;
}
}  // namespace
int main() {
  Recorder metrics;
  assert(fitText(metrics, "ABC", Font::Body, 24) == "ABC");
  assert(fitText(metrics, "ABCDEFG", Font::Body, 48) == "ABC...");
  assert(fitText(metrics, "ABCDEFG", Font::Body, 16).empty());
  assert(fitText(metrics, "ABCDEFG", Font::Body, 0).empty());
  assert(fitText(metrics, "\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9\xc3\xa9", Font::Body, 40) ==
         "\xc3\xa9\xc3\xa9...");
  assert(
      fitText(metrics,
              "A\xf0\x9f\x8c\x85\xf0\x9f\x8c\x85\xf0\x9f\x8c\x85\xf0\x9f\x8c\x85\xf0\x9f\x8c\x85",
              Font::Body, 40) == "A\xf0\x9f\x8c\x85...");
  auto list = sample();
  Recorder first;
  render(first, list);
  assert(first.find("East window").y >= layout::Rows[0].y);
  assert(first.find("East window").y < layout::Rows[0].y + layout::Rows[0].height);
  first.find("1 / 2");
  first.find("Shades");
  first.find("Groups");
  auto detail = list;
  detail.screen = Screen::Detail;
  detail.title = "Living room";
  detail.controls_enabled = true;
  Recorder enabled;
  render(enabled, detail);
  enabled.find("Living room");
  assert(layout::Open.contains(enabled.find("Open").x, enabled.find("Open").y));
  assert(layout::Close.contains(enabled.find("Close").x, enabled.find("Close").y));
  const auto activeColor = enabled.find("Open").color;
  detail.controls_enabled = false;
  detail.status = "Busy";
  detail.message = "Another request is active";
  Recorder busy;
  render(busy, detail);
  busy.find("Another request is active");
  busy.find("Busy");
  assert(busy.find("Open").color != activeColor);
  detail.status = "Storage fault";
  detail.message = "Storage unavailable";
  detail.message_error = true;
  Recorder blocked;
  render(blocked, detail);
  blocked.find("Storage unavailable");
  blocked.find("Storage fault");
  list.rows.clear();
  list.total = 0;
  list.pages = 1;
  Recorder empty;
  render(empty, list);
  empty.find("No shades configured");
  list.tab = Tab::Groups;
  Recorder groups;
  render(groups, list);
  groups.find("No groups configured");
  std::cout << "UI renderer bounds, UTF-8 fitting and action geometry passed\n";
}
