// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
// Native SVG preview of the same renderer used by the device. Font metrics are
// approximations; physical fonts, touch and SPI require device qualification.
#include <iomanip>
#include <iostream>
#include <sstream>
#include <string>

#include "ui_renderer.h"

using namespace platinum::ui;
namespace {
std::string escape(const std::string& s) {
  std::string out;
  for (char ch : s) {
    switch (ch) {
      case '&':
        out += "&amp;";
        break;
      case '<':
        out += "&lt;";
        break;
      case '>':
        out += "&gt;";
        break;
      case '"':
        out += "&quot;";
        break;
      default:
        out += ch;
    }
  }
  return out;
}
std::string color(uint32_t value) {
  std::ostringstream s;
  s << '#' << std::hex << std::setfill('0') << std::setw(6) << value;
  return s.str();
}
struct Svg final : Canvas {
  void rectangle(const Rect& r, uint32_t c, int radius = 0) override {
    std::cout << "<rect x=\"" << r.x << "\" y=\"" << r.y << "\" width=\"" << r.width
              << "\" height=\"" << r.height << "\" rx=\"" << radius << "\" fill=\"" << color(c)
              << "\"/>\n";
  }
  int textWidth(const std::string& s, Font font) override {
    int count = 0;
    for (unsigned char ch : s)
      if ((ch & 0xc0) != 0x80)
        ++count;
    return count * (font == Font::Small ? 7 : font == Font::Body ? 8 : 11);
  }
  void text(int x, int y, const std::string& value, Font font, uint32_t c) override {
    int size = font == Font::Small ? 12 : font == Font::Body ? 16 : 20;
    std::cout << "<text x=\"" << x << "\" y=\"" << y + size
              << "\" font-family=\"DejaVu Sans, sans-serif\" font-size=\"" << size << "\" fill=\""
              << color(c) << "\">" << escape(value) << "</text>\n";
  }
};
}  // namespace
int main(int argc, char** argv) {
  std::string mode = argc > 1 ? argv[1] : "shades";
  View v;
  v.total = 4;
  v.pages = 2;
  v.rows = {
      {0, "East window", 1, true}, {1, "West window", 1, true}, {2, "Blackout shade", 1, false}};
  if (mode == "groups") {
    v.tab = Tab::Groups;
    v.total = 2;
    v.pages = 1;
    v.rows = {{0, "Living room", 2, true}, {1, "Bedroom", 1, false}};
  } else if (mode == "detail" || mode == "disabled") {
    v.screen = Screen::Detail;
    v.tab = Tab::Groups;
    v.title = "Living room";
    v.member_count = 2;
    v.controls_enabled = true;
    if (mode == "disabled") {
      v.status = "Busy";
      v.controls_enabled = false;
      v.message = "Another request is active";
    }
  } else if (mode != "shades") {
    std::cerr << "usage: preview_screen [shades|groups|detail|disabled]\n";
    return 2;
  }
  std::cout << "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"960\" height=\"720\" viewBox=\"0 "
               "0 320 240\">\n";
  Svg canvas;
  render(canvas, v);
  std::cout << "</svg>\n";
}
