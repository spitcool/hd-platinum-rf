// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
// Local-only, persistent stdin simulator. Uses the production engine, touch
// model and renderer; submitted jobs complete without any hardware or RF I/O.
#include <charconv>
#include <chrono>
#include <cstdint>
#include <deque>
#include <iomanip>
#include <iostream>
#include <memory>
#include <sstream>
#include <stdexcept>
#include <string>
#include <string_view>
#include <vector>

#include "ui_renderer.h"

namespace {
using namespace platinum;
using namespace platinum::ui;
using SteadyClock = std::chrono::steady_clock;
constexpr size_t MaxProtocolLine = MaxInput + 64;

std::string jsonString(const std::string& value) {
  static const char Hex[] = "0123456789abcdef";
  std::string out = "\"";
  for (unsigned char ch : value) {
    if (ch == '"' || ch == '\\') {
      out += '\\';
      out += char(ch);
    } else if (ch < 32) {
      out += "\\u00";
      out += Hex[ch >> 4];
      out += Hex[ch & 15];
    } else {
      out += char(ch);
    }
  }
  out += '"';
  return out;
}

bool validUtf8(const std::string& text) {
  for (size_t i = 0; i < text.size();) {
    const auto first = uint8_t(text[i++]);
    if (first < 0x80)
      continue;
    unsigned remaining, codepoint, minimum;
    if (first >= 0xc2 && first <= 0xdf) {
      remaining = 1;
      codepoint = first & 31;
      minimum = 0x80;
    } else if (first >= 0xe0 && first <= 0xef) {
      remaining = 2;
      codepoint = first & 15;
      minimum = 0x800;
    } else if (first >= 0xf0 && first <= 0xf4) {
      remaining = 3;
      codepoint = first & 7;
      minimum = 0x10000;
    } else {
      return false;
    }
    if (remaining > text.size() - i)
      return false;
    while (remaining--) {
      const auto next = uint8_t(text[i++]);
      if ((next & 0xc0) != 0x80)
        return false;
      codepoint = (codepoint << 6) | (next & 63);
    }
    if (codepoint < minimum || codepoint > 0x10ffff || (codepoint >= 0xd800 && codepoint <= 0xdfff))
      return false;
  }
  return true;
}

std::string xmlText(const std::string& value) {
  std::string out;
  for (char ch : value) {
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
  std::ostringstream out;
  out << '#' << std::hex << std::setfill('0') << std::setw(6) << value;
  return out.str();
}

// Match the portable preview's font approximation. The same render() function
// supplies all geometry, colors, labels and control availability as the device.
struct Svg final : Canvas {
  std::ostringstream out;
  Svg() {
    out << "<svg xmlns=\"http://www.w3.org/2000/svg\" width=\"320\" height=\"240\" "
           "viewBox=\"0 0 320 240\">";
  }
  void rectangle(const Rect& r, uint32_t c, int radius = 0) override {
    out << "<rect x=\"" << r.x << "\" y=\"" << r.y << "\" width=\"" << r.width << "\" height=\""
        << r.height << "\" rx=\"" << radius << "\" fill=\"" << color(c) << "\"/>";
  }
  int textWidth(const std::string& text, Font font) override {
    int count = 0;
    for (unsigned char ch : text)
      if ((ch & 0xc0) != 0x80)
        ++count;
    return count * (font == Font::Small ? 7 : font == Font::Body ? 8 : 11);
  }
  void text(int x, int y, const std::string& value, Font font, uint32_t c) override {
    const int size = font == Font::Small ? 12 : font == Font::Body ? 16 : 20;
    out << "<text x=\"" << x << "\" y=\"" << y + size
        << "\" font-family=\"DejaVu Sans, sans-serif\" font-size=\"" << size << "\" fill=\""
        << color(c) << "\">" << xmlText(value) << "</text>";
  }
  std::string finish() {
    out << "</svg>";
    return out.str();
  }
};

State sampleInventory() {
  State state;
  state.mac = "020000000001";
  state.rooms = {
      {0, 1, 0x1234, "Living room"}, {1, 1, 0x2345, "Bedroom"}, {2, 1, 0x3456, "Office"}};
  constexpr uint32_t Position = 1u << 4;
  constexpr uint32_t Service = Position | (1u << 1) | (1u << 12);
  state.shades = {{0, 0, 1, "East window", Service, {{4, 128}}},
                  {1, 0, 2, "West window", Position, {{4, 255}}},
                  {2, 1, 1, "Blackout shade", Service, {{4, 0}}},
                  {3, 1, 2, "Sheer shade", Position, {{4, 192}}},
                  {4, 2, 1, "Desk window", Position, {{4, 96}}},
                  {5, 2, 2, "Side window", Position, {}}};
  return state;
}

int integer(std::string_view text) {
  int value = 0;
  auto result = std::from_chars(text.data(), text.data() + text.size(), value);
  if (result.ec != std::errc{} || result.ptr != text.data() + text.size())
    throw std::invalid_argument("Invalid touch coordinate");
  return value;
}

class Simulator {
 public:
  Simulator() {
    reset();
  }
  void request(const std::string& line, bool oversized) {
    accepted_ = true;
    error_.clear();
    started_ = false;
    finished_ = false;
    finished_ok_ = false;
    finishJob();
    try {
      if (oversized)
        throw std::invalid_argument("Protocol line is too long");
      if (!validUtf8(line))
        throw std::invalid_argument("Protocol line is not valid UTF-8");
      if (line == "state") {
        // Polling advances only finite submitted jobs, without replay or RF I/O.
      } else if (line == "reset") {
        reset();
      } else if (line == "cancel") {
        model_.cancelTouch();
      } else if (line.rfind("command\t", 0) == 0) {
        dispatch(line.substr(8));
      } else if (line.rfind("touch\t", 0) == 0) {
        touch(line);
      } else {
        throw std::invalid_argument("Unknown simulator request");
      }
    } catch (const std::exception& e) {
      fail(e.what());
    }
  }
  std::string response() {
    Svg canvas;
    render(canvas, model_.view(engine_->state(), runtime()));
    const auto& state = engine_->state();
    std::ostringstream out;
    out << "{\"svg\":" << jsonString(canvas.finish()) << ",\"rooms\":[";
    bool first = true;
    for (const auto& room : state.rooms) {
      if (!first)
        out << ',';
      first = false;
      out << "{\"id\":" << unsigned(room.id) << ",\"name\":" << jsonString(room.name) << '}';
    }
    out << "],\"shades\":[";
    first = true;
    for (const auto& shade : state.shades) {
      if (!first)
        out << ',';
      first = false;
      int position = -1;
      for (const auto& p : shade.requested)
        if (p.feature == 4)
          position = p.value;
      const std::string room = shade.room < state.rooms.size() ? state.rooms[shade.room].name : "";
      out << "{\"id\":" << unsigned(shade.id) << ",\"room_id\":" << unsigned(shade.room)
          << ",\"room\":" << jsonString(room) << ",\"name\":" << jsonString(shade.name)
          << ",\"enabled\":" << ((shade.enabled_features & (1u << 4)) ? "true" : "false")
          << ",\"features\":" << shade.enabled_features << ",\"position\":";
      if (position < 0)
        out << "null";
      else
        out << position;
      out << '}';
    }
    out << "],\"busy\":" << (engine_->busy() ? "true" : "false")
        << ",\"status\":" << jsonString(status_) << ",\"events\":[";
    first = true;
    for (const auto& event : events_) {
      if (!first)
        out << ',';
      first = false;
      out << jsonString(event);
    }
    out << "],\"command\":" << jsonString(command_)
        << ",\"accepted\":" << (accepted_ ? "true" : "false") << ",\"error\":" << jsonString(error_)
        << ",\"started\":" << (started_ ? "true" : "false")
        << ",\"finished\":" << (finished_ ? "true" : "false")
        << ",\"finished_ok\":" << (finished_ok_ ? "true" : "false") << '}';
    return out.str();
  }

 private:
  Runtime runtime() const {
    Runtime result;
    result.busy = engine_->busy();
    return result;
  }
  void event(std::string text) {
    if (events_.size() == 30)
      events_.pop_front();
    events_.push_back(std::move(text));
  }
  void records(const std::vector<Record>& replies) {
    for (const auto& reply : replies)
      event(reply.payload);
  }
  void fail(const std::string& message) {
    accepted_ = false;
    error_ = message;
    status_ = "failed";
    model_.feedback(message, true);
    event(message);
  }
  void reset() {
    model_ = Model{};
    events_.clear();
    command_.clear();
    error_.clear();
    accepted_ = true;
    started_ = false;
    finished_ = false;
    finished_ok_ = false;
    status_ = "idle";
    job_.clear();
    cancelled_ = false;
    next_identity_ = 0x4000;
    Hooks hooks;
    hooks.persist = [](const State&) { return true; };
    hooks.submit = [this](const std::vector<RadioCommand>& commands) {
      if (!job_.empty())
        return false;
      job_ = commands;
      started_ = true;
      deadline_ = SteadyClock::now() + std::chrono::milliseconds(900);
      cancelled_ = false;
      status_ = "running";
      event("Accepted " + std::to_string(commands.size()) +
            (commands.size() == 1 ? " shade request" : " shade requests"));
      return true;
    };
    hooks.random16 = [this]() { return ++next_identity_; };
    hooks.cancel = [this]() {
      cancelled_ = true;
      deadline_ = SteadyClock::now();
    };
    engine_ = std::make_unique<Engine>(sampleInventory(), std::move(hooks));
    if (!engine_->valid())
      throw std::runtime_error("Invalid sample inventory");
    event("Sample inventory loaded");
  }
  void finishJob() {
    if (job_.empty() || SteadyClock::now() < deadline_)
      return;
    records(engine_->complete(!cancelled_));
    finished_ = true;
    finished_ok_ = !cancelled_;
    job_.clear();
    status_ = cancelled_ ? "failed" : "completed";
    const std::string message = cancelled_ ? "Request cancelled" : "Request accepted";
    model_.feedback(message, cancelled_);
    event(message);
  }
  void dispatch(const std::string& command) {
    if (command.empty() || command.size() > MaxInput ||
        !validateTransaction(engine_->state(), command)) {
      fail("Invalid or unavailable command");
      return;
    }
    command_ = command;
    event("Command " + command);
    Session session;
    const auto replies = engine_->feed(session, command);
    records(replies);
    bool failed = session.closed || !session.pending.empty() || !session.staged.empty();
    std::string error = "Command was not accepted";
    for (const auto& reply : replies) {
      if (reply.payload.rfind("$error", 0) != 0)
        continue;
      failed = true;
      if (reply.payload == "$error93-")
        error = "Another command is busy";
      else if (reply.payload == "$error92-")
        error = "Target is not enabled";
    }
    if (failed) {
      fail(error);
    } else {
      status_ = engine_->busy() ? "running" : "completed";
      model_.feedback(engine_->busy() ? "Sending request..." : "Request accepted");
    }
  }
  void touch(const std::string& line) {
    const size_t first = line.find('\t', 6);
    const size_t second = first == std::string::npos ? first : line.find('\t', first + 1);
    if (first == std::string::npos || second == std::string::npos ||
        line.find('\t', second + 1) != std::string::npos)
      throw std::invalid_argument("Expected touch, pressed, x and y fields");
    const auto down = std::string_view(line).substr(6, first - 6);
    if (down != "0" && down != "1")
      throw std::invalid_argument("Pressed must be 0 or 1");
    const int x = integer(std::string_view(line).substr(first + 1, second - first - 1));
    const int y = integer(std::string_view(line).substr(second + 1));
    auto command = model_.touch(down == "1", x, y, engine_->state(), runtime());
    if (!command.empty())
      dispatch(command);
  }
  std::unique_ptr<Engine> engine_;
  Model model_;
  std::vector<RadioCommand> job_;
  SteadyClock::time_point deadline_{};
  std::deque<std::string> events_;
  std::string command_, status_ = "idle", error_;
  uint16_t next_identity_ = 0;
  bool cancelled_ = false, accepted_ = true;
  bool started_ = false, finished_ = false, finished_ok_ = false;
};

// Drain oversized requests through newline without retaining unbounded input.
bool readLine(std::string& line, bool& oversized) {
  line.clear();
  oversized = false;
  bool found = false;
  char ch;
  while (std::cin.get(ch)) {
    found = true;
    if (ch == '\n')
      break;
    if (line.size() < MaxProtocolLine)
      line += ch;
    else
      oversized = true;
  }
  if (!line.empty() && line.back() == '\r')
    line.pop_back();
  return found;
}
}  // namespace

int main() {
  try {
    Simulator simulator;
    std::string line;
    bool oversized;
    while (readLine(line, oversized)) {
      simulator.request(line, oversized);
      std::cout << simulator.response() << '\n' << std::flush;
      if (!std::cout)
        return 1;
    }
  } catch (const std::exception& e) {
    std::cerr << "Simulator stopped: " << e.what() << '\n';
    return 1;
  }
}
