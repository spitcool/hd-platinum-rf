// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

#include <cstdint>
#include <string>

#include "ui_model.h"
#ifdef ARDUINO
#include <M5GFX.h>
#endif

namespace platinum {
namespace ui {
// RGB888 colors; implementations convert to their own framebuffer format.
enum class Font : uint8_t { Small, Body, Title };
class Canvas {
 public:
  virtual ~Canvas() = default;
  virtual void rectangle(const Rect& rect, uint32_t color, int radius = 0) = 0;
  virtual void text(int x, int y, const std::string& value, Font font, uint32_t color) = 0;
  virtual int textWidth(const std::string& value, Font font) = 0;
};

// Truncate only at a UTF-8 code-point boundary. Fitting uses the actual canvas
// font metrics; missing glyphs are a font limitation, not a change to stored names.
std::string fitText(Canvas& canvas, const std::string& value, Font font, int width);
// Paint exactly one 320x240 frame into an off-screen Canvas. This never owns or
// accesses the LCD/network SPI bus and cannot dispatch a shade operation.
void render(Canvas& canvas, const View& view);

#ifdef ARDUINO
// Pass an already allocated 320x240 RGB565 M5Canvas. The caller owns its lifetime
// and pushes the completed sprite only while holding display-bus ownership.
class SpriteCanvas final : public Canvas {
 public:
  explicit SpriteCanvas(M5Canvas& sprite) : sprite_(sprite) {}
  void rectangle(const Rect& rect, uint32_t color, int radius = 0) override;
  void text(int x, int y, const std::string& value, Font font, uint32_t color) override;
  int textWidth(const std::string& value, Font font) override;

 private:
  void selectFont(Font font);
  M5Canvas& sprite_;
};
#endif
}  // namespace ui
}  // namespace platinum
