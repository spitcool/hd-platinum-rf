// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include "ui_renderer.h"

#include <algorithm>

namespace platinum {
namespace ui {
namespace {
constexpr uint32_t Background = 0xf0f4f7, Surface = 0xffffff, Ink = 0x192e40, Muted = 0x607487,
                   Header = 0x192e40, Accent = 0x195e94, Green = 0x22765d, Warning = 0x935c00,
                   WarningTint = 0xffedc8, Error = 0x9e3939, ErrorTint = 0xffe4e0,
                   Disabled = 0xdbe3e9;

int fontHeight(Font font) {
  return font == Font::Small ? 15 : font == Font::Body ? 16 : 22;
}
void label(Canvas& canvas, int x, int y, int width, const std::string& value, Font font,
           uint32_t color) {
  canvas.text(x, y, fitText(canvas, value, font, width), font, color);
}
void centered(Canvas& canvas, const Rect& rect, const std::string& value, Font font,
              uint32_t color) {
  auto fitted = fitText(canvas, value, font, rect.width - 12);
  canvas.text(rect.x + (rect.width - canvas.textWidth(fitted, font)) / 2,
              rect.y + (rect.height - fontHeight(font)) / 2, fitted, font, color);
}
void button(Canvas& canvas, const Rect& rect, const std::string& caption, bool enabled,
            uint32_t color = Accent, Font font = Font::Body) {
  canvas.rectangle(rect, enabled ? color : Disabled, 7);
  centered(canvas, rect, caption, font, enabled ? Surface : Muted);
}
void status(Canvas& canvas, const View& view) {
  if (view.status.empty())
    return;
  uint32_t color = Accent;
  if (view.status == "Busy")
    color = Warning;
  else if (view.status == "Storage fault" || view.status == "Radio offline")
    color = Error;
  canvas.rectangle({186, 4, 126, 23}, color, 6);
  centered(canvas, {186, 4, 126, 23}, view.status, Font::Small, Surface);
}
void list(Canvas& canvas, const View& view) {
  label(canvas, 12, 7, 166, "PLATINUM", Font::Body, Surface);
  status(canvas, view);
  auto tab = [&](const Rect& rect, const std::string& title, bool selected) {
    canvas.rectangle(rect, selected ? Accent : Surface, 6);
    centered(canvas, rect, title, Font::Body, selected ? Surface : Muted);
  };
  tab(layout::ShadesTab, "Shades", view.tab == Tab::Shades);
  tab(layout::GroupsTab, "Groups", view.tab == Tab::Groups);
  if (view.rows.empty()) {
    canvas.rectangle({8, 70, 304, 130}, Surface, 8);
    centered(canvas, {12, 120, 296, 30},
             view.tab == Tab::Shades ? "No shades configured" : "No groups configured", Font::Body,
             Ink);
  }
  for (size_t i = 0; i < std::min(view.rows.size(), layout::RowsPerPage); ++i) {
    const auto& row = view.rows[i];
    const auto& rect = layout::Rows[i];
    canvas.rectangle(rect, Surface, 7);
    label(canvas, rect.x + 10, rect.y + 13, rect.width - 44, row.name, Font::Body, Ink);
    centered(canvas, {rect.x + rect.width - 28, rect.y + 5, 24, 30}, ">", Font::Body,
             row.enabled ? Accent : Muted);
  }
  button(canvas, layout::Previous, "Prev", view.page > 0);
  button(canvas, layout::Next, "Next", view.page + 1 < view.pages);
  centered(canvas, {78, 206, 164, 28},
           std::to_string(view.page + 1) + " / " + std::to_string(view.pages), Font::Small, Muted);
}
void detail(Canvas& canvas, const View& view) {
  button(canvas, layout::Back, "Back", true);
  status(canvas, view);
  centered(canvas, {6, 46, 308, 38}, view.title, Font::Title, Ink);
  button(canvas, layout::Open, "Open", view.controls_enabled, Green, Font::Title);
  button(canvas, layout::Close, "Close", view.controls_enabled, Accent, Font::Title);

  if (view.message.empty())
    return;
  if (view.message_error)
    canvas.rectangle({8, 211, 304, 25}, ErrorTint, 5);
  else if (!view.controls_enabled)
    canvas.rectangle({8, 211, 304, 25}, WarningTint, 5);
  label(canvas, 12, 215, 296, view.message, Font::Small,
        view.message_error       ? Error
        : !view.controls_enabled ? Warning
                                 : Muted);
}
}  // namespace

std::string fitText(Canvas& canvas, const std::string& value, Font font, int width) {
  if (width <= 0)
    return {};
  if (canvas.textWidth(value, font) <= width)
    return value;
  const std::string suffix = "...";
  if (canvas.textWidth(suffix, font) > width)
    return {};
  std::string shortened = value;
  while (!shortened.empty()) {
    size_t at = shortened.size() - 1;
    while (at > 0 && (static_cast<uint8_t>(shortened[at]) & 0xc0) == 0x80)
      --at;
    shortened.resize(at);
    if (canvas.textWidth(shortened + suffix, font) <= width)
      return shortened + suffix;
  }
  return suffix;
}
void render(Canvas& canvas, const View& view) {
  canvas.rectangle({0, 0, layout::Width, layout::Height}, Background);
  canvas.rectangle({0, 0, layout::Width, 30}, Header);
  if (view.screen == Screen::List)
    list(canvas, view);
  else
    detail(canvas, view);
}

#ifdef ARDUINO
void SpriteCanvas::selectFont(Font font) {
  sprite_.setTextSize(1);
  sprite_.setTextDatum(lgfx::textdatum_t::top_left);
  sprite_.setTextWrap(false, false);
  sprite_.setFont(font == Font::Small   ? &lgfx::fonts::DejaVu12
                  : font == Font::Title ? &lgfx::fonts::DejaVu18
                                        : static_cast<const lgfx::IFont*>(&lgfx::fonts::Font2));
}
void SpriteCanvas::rectangle(const Rect& rect, uint32_t color, int radius) {
  if (radius)
    sprite_.fillRoundRect(rect.x, rect.y, rect.width, rect.height, radius, color);
  else
    sprite_.fillRect(rect.x, rect.y, rect.width, rect.height, color);
}
void SpriteCanvas::text(int x, int y, const std::string& value, Font font, uint32_t color) {
  selectFont(font);
  sprite_.setTextColor(color);
  sprite_.drawString(value.c_str(), x, y);
}
int SpriteCanvas::textWidth(const std::string& value, Font font) {
  selectFont(font);
  return sprite_.textWidth(value.c_str());
}
#endif
}  // namespace ui
}  // namespace platinum
