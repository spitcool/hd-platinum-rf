// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include <Arduino.h>
#include <ArduinoJson.h>
#include <Ethernet.h>
#include <EthernetUdp.h>
#include <M5Unified.h>
#include <Preferences.h>
#include <WiFi.h>
#include <WiFiUdp.h>
#include <esp_mac.h>
#include <lwip/sockets.h>

#include <atomic>
#include <cerrno>
#include <memory>

#include "discovery.h"
#include "display_bus.h"
#include "gateway_core.h"
#include "gateway_radio.h"
#include "http_protocol.h"
#include "output_buffer.h"
#include "sequence_store.h"
#include "ui_model.h"
#include "ui_renderer.h"
#include "web_ui.h"

#ifdef GATEWAY_CONFIG_HEADER
#include GATEWAY_CONFIG_HEADER
#elif __has_include("gateway_config.h")
#include "gateway_config.h"
#endif
#ifndef GATEWAY_WIFI_SSID
#define GATEWAY_WIFI_SSID ""
#define GATEWAY_WIFI_PASSWORD ""
#endif
#ifndef GATEWAY_CLIENT_NETWORK
#define GATEWAY_CLIENT_NETWORK "0.0.0.0"
#define GATEWAY_CLIENT_MASK "0.0.0.0"
#endif
#ifndef GATEWAY_API_TOKEN
#define GATEWAY_API_TOKEN ""
#endif
#ifndef GATEWAY_HTTP_HOST
#define GATEWAY_HTTP_HOST ""
#endif
#ifndef GATEWAY_SCREEN_ENABLED
#define GATEWAY_SCREEN_ENABLED true
#endif
#ifndef GATEWAY_TCP_ENABLED
#define GATEWAY_TCP_ENABLED true
#endif
#ifndef GATEWAY_HTTP_ENABLED
#define GATEWAY_HTTP_ENABLED true
#endif
#ifndef GATEWAY_WEB_ENABLED
#define GATEWAY_WEB_ENABLED true
#endif
#ifndef GATEWAY_RF_ENABLED
#define GATEWAY_RF_ENABLED false
#endif
#ifndef GATEWAY_RF_QUALIFIED
#define GATEWAY_RF_QUALIFIED false
#endif

#if GATEWAY_NETWORK_WIFI
using NetClient = WiFiClient;
using NetServer = WiFiServer;
using NetUDP = WiFiUDP;
#else
using NetClient = EthernetClient;
using NetUDP = EthernetUDP;
// ESP32 Arduino's Server base uses begin(port), while Ethernet 2.0.2 has
// begin(). The port is fixed by the constructor; bridge only that API mismatch.
class NetServer final : public EthernetServer {
 public:
  explicit NetServer(uint16_t port) : EthernetServer(port) {}
  void begin(uint16_t = 0) override {
    EthernetServer::begin();
  }
};
#endif
namespace {
constexpr unsigned ClientCount = 3, MaxOutput = 65536;
NetServer lan(522), http(8077);
NetUDP udp;
Preferences database;
std::unique_ptr<platinum::Engine> engine;
platinum::display::ArduinoDisplayBus displayBus;
M5Canvas screenSprite(&M5.Display);
platinum::ui::SpriteCanvas screenCanvas(screenSprite);
platinum::ui::Model screenModel;
platinum::ui::View lastScreenView;
bool screenReady = false, screenDrawn = false, screenActionPending = false;
bool touchActive = false, touchBlocked = false;
uint8_t touchId = 0;
int touchX = 0, touchY = 0;
uint32_t lastTouchPoll = 0, lastScreenDraw = 0;
platinum::radio::ArduinoIo radioIo;
platinum::radio::Radio radio(radioIo);
QueueHandle_t jobs = nullptr, results = nullptr;
std::atomic<bool> abortRadio{false};
bool storageHealthy = false, networkStarted = false;
std::atomic<bool> radioReady{false}, sequenceReady{false};
bool lanRunning = false, httpRunning = false;
struct ServiceSettings {
  bool tcp522 = GATEWAY_TCP_ENABLED, http = GATEWAY_HTTP_ENABLED, web = GATEWAY_WEB_ENABLED;
} services;
struct OperationStatus {
  std::string id;
  std::string status = "idle";
} operation;
uint32_t lastTick = 0, lastNetworkTry = 0, discoveryWindow = 0;
#if !GATEWAY_NETWORK_WIFI
uint32_t lastDhcp = 0;
#endif
unsigned discoveryReplies = 0;
IPAddress allowedNetwork, allowedMask;
struct Peer {
  NetClient client;
  platinum::Session session;
  std::string output;
  uint32_t touched = 0, fragmentSince = 0, outputProgress = 0;
};
Peer peers[ClientCount];
struct HttpPeer {
  NetClient client;
  std::string input;
  platinum::http::OutputBuffer output;
  uint32_t start = 0;
} web;
std::string serialInput;
bool serialOverflow = false;
struct CachedRequest {
  std::string id, command;
  String response;
  int status;
};
std::vector<CachedRequest> requestCache;  // Bounded per-boot retry deduplication.
size_t cacheBytes = 0;
bool saveServices(ServiceSettings candidate) {
  if (!storageHealthy)
    return false;
  uint8_t bits =
      uint8_t(candidate.tcp522) | (uint8_t(candidate.http) << 1) | (uint8_t(candidate.web) << 2);
  if (database.putUChar("services", bits) != 1 || database.getUChar("services", 255) != bits) {
    storageHealthy = false;
    return false;
  }
  services = candidate;
  return true;
}
platinum::radio::SequenceHooks sequenceHooks(Preferences& store, bool opened) {
  platinum::radio::SequenceHooks hooks;
  hooks.read = [&store, opened](uint32_t& value) {
    using platinum::radio::SequenceRead;
    if (!opened)
      return SequenceRead::Failure;
    if (!store.isKey("next"))
      return SequenceRead::Absent;
    if (store.getType("next") != PT_U32)
      return SequenceRead::Corrupt;
    value = store.getUInt("next", 65537);
    return value <= 65536 ? SequenceRead::Present : SequenceRead::Corrupt;
  };
  hooks.write = [&store, opened](uint32_t value) {
    return opened && store.putUInt("next", value) == sizeof(value);
  };
  return hooks;
}

IPAddress address() {
#if GATEWAY_NETWORK_WIFI
  return WiFi.localIP();
#else
  return Ethernet.localIP();
#endif
}
bool allowed(IPAddress ip) {
  uint32_t mask = uint32_t(allowedMask);
  return mask && (uint32_t(ip) & mask) == (uint32_t(allowedNetwork) & mask);
}
bool localNetworkConfig() {
  if (!allowedNetwork.fromString(GATEWAY_CLIENT_NETWORK) ||
      !allowedMask.fromString(GATEWAY_CLIENT_MASK))
    return false;
  // Only explicit private networks. Reject holes in netmask, public space, /0.
  uint32_t mask = 0, net = 0;
  for (int i = 0; i < 4; ++i) {
    mask = (mask << 8) | allowedMask[i];
    net = (net << 8) | allowedNetwork[i];
  }
  const uint32_t inv = ~mask;
  if (!mask || (inv & (inv + 1)) || (net & inv))
    return false;
  const bool privateNet =
      (allowedNetwork[0] == 10 && mask >= 0xff000000u) ||
      (allowedNetwork[0] == 172 && allowedNetwork[1] >= 16 && allowedNetwork[1] <= 31 &&
       mask >= 0xfff00000u) ||
      (allowedNetwork[0] == 192 && allowedNetwork[1] == 168 && mask >= 0xffff0000u) ||
      (allowedNetwork[0] == 169 && allowedNetwork[1] == 254 && mask >= 0xffff0000u);
  if (!privateNet)
    allowedMask = IPAddress(0, 0, 0, 0);
  return privateNet;
}
bool saveState(const platinum::State& state) {
  if (!storageHealthy)
    return false;
  auto bytes = platinum::encodeState(state);
  if (bytes.empty() || database.putBytes("state", bytes.data(), bytes.size()) != bytes.size()) {
    storageHealthy = false;
    return false;
  }
  std::string check(bytes.size(), '\0');
  if (database.getBytes("state", &check[0], check.size()) != check.size() || check != bytes) {
    storageHealthy = false;
    return false;
  }
  return true;
}
void queueRecords(const std::vector<platinum::Record>& records, int origin = -1) {
  for (const auto& r : records)
    for (unsigned i = 0; i < ClientCount; ++i) {
      if (!peers[i].client || (!r.broadcast && int(i) != origin))
        continue;
      auto line = std::to_string(i + 1) + " " + r.payload + "\n\r";
      if (peers[i].output.size() + line.size() > MaxOutput) {
        peers[i].client.stop();
        continue;
      }
      peers[i].output += line;
    }
}
// A separately owned task is the only code allowed to touch the packet radio.
// Queue length one + Engine::busy keep admission bounded across TCP and HTTP.
void radioTask(void*) {
  Preferences sequence;
  const bool sequenceOpen = sequence.begin("platinum-seq", false);
  auto hooks = sequenceHooks(sequence, sequenceOpen);
  uint32_t initialOrdinal = 65537;
  sequenceReady = hooks.read(initialOrdinal) == platinum::radio::SequenceRead::Present &&
                  initialOrdinal < 65536;
  platinum::radio::SequenceStore allocator(std::move(hooks));
  for (;;) {
    std::vector<platinum::RadioCommand>* batch = nullptr;
    if (xQueueReceive(jobs, &batch, portMAX_DELAY) != pdTRUE)
      continue;
    bool ok = true;
    for (const auto& c : *batch) {
      if (abortRadio) {
        ok = false;
        break;
      }
      if (!GATEWAY_RF_ENABLED) {
        vTaskDelay(pdMS_TO_TICKS(1));
        continue;
      }
      if (!sequenceOpen || !sequence.isKey("next") || !radioReady) {
        ok = false;
        break;
      }
      auto ordinal = allocator.allocate();
      if (!ordinal) {
        sequenceReady = false;
        ok = false;
        break;
      }
      if (*ordinal == 65535)
        sequenceReady = false;
      // Never return a reserved ordinal, including timeout, cancellation or reset.
      platinum::radio::Command command;
      command.room_id = {uint8_t(c.rf_id >> 8), uint8_t(c.rf_id)};
      command.mask = c.mask;
      command.position = c.value;
      command.operation_enabled = true;
      if (c.feature == 4)
        command.operation = platinum::radio::Operation::Position;
      else if (c.feature == 1)
        command.operation = platinum::radio::Operation::Sync;
      else if (c.feature == 12)
        command.operation = platinum::radio::Operation::Jog;
      else {
        ok = false;
        break;
      }
      const auto receipt = radio.transmit(command, *ordinal);
      ok = receipt.code == platinum::radio::ResultCode::Submitted;
      if (!ok) {
        radioReady = false;
        break;
      }
    }
    delete batch;
    xQueueSend(results, &ok, portMAX_DELAY);
  }
}
bool submit(const std::vector<platinum::RadioCommand>& commands) {
  if (!storageHealthy || !jobs || commands.empty())
    return false;
  // Secondary features are accepted for simulation only until their RF is qualified.
  if (GATEWAY_RF_ENABLED) {
    if (!GATEWAY_RF_QUALIFIED || !radioReady)
      return false;
    for (const auto& c : commands)
      if (c.feature != 1 && c.feature != 4 && c.feature != 12)
        return false;
  }
  auto* batch = new (std::nothrow) std::vector<platinum::RadioCommand>(commands);
  if (!batch)
    return false;
  abortRadio = false;
  if (xQueueSend(jobs, &batch, 0) != pdTRUE) {
    delete batch;
    return false;
  }
  operation = {"", "submitted"};
  return true;
}
bool networkBusReady() {
  return GATEWAY_NETWORK_WIFI || !GATEWAY_SCREEN_ENABLED || displayBus.networkReady();
}
platinum::ui::Runtime screenRuntime() {
  platinum::ui::Runtime runtime;
  runtime.busy = engine->busy();
  runtime.storage_ok = storageHealthy && engine->valid();
  runtime.backend_ready =
      !GATEWAY_RF_ENABLED || (GATEWAY_RF_QUALIFIED && radioReady && sequenceReady);
  return runtime;
}
bool drawScreen(const platinum::ui::View& view) {
  if (!screenReady)
    return false;
  // CPU drawing only touches the PSRAM sprite. SPI ownership surrounds the
  // synchronous transfer; no network call or RF task uses this display bus.
  platinum::ui::render(screenCanvas, view);
  if (!displayBus.acquireDisplay()) {
    screenReady = false;
    screenModel.cancelTouch();
    return false;
  }
  screenSprite.pushSprite(0, 0);
  displayBus.releaseDisplay();
  if (!displayBus.available()) {
    screenReady = false;
    screenModel.cancelTouch();
    return false;
  }
  lastScreenView = view;
  screenDrawn = true;
  lastScreenDraw = millis();
  return true;
}
void screenCommand(const std::string& command) {
  if (command.empty() || !screenReady)
    return;
  // A local click has the same validation and operation grants as HTTP/TCP.
  // Paint the busy state before admitting physical work, then defer LCD writes
  // until that finite job finishes to avoid competing with radio timing.
  auto pending = screenRuntime();
  pending.busy = true;
  if (!drawScreen(screenModel.view(engine->state(), pending)))
    return;
  platinum::Session session;
  auto replies = engine->feed(session, command);
  queueRecords(replies);
  bool failed = session.closed || !session.pending.empty() || !session.staged.empty();
  std::string message = "Command was not accepted";
  for (const auto& reply : replies)
    if (reply.payload.rfind("$error", 0) == 0) {
      failed = true;
      if (reply.payload == "$error92-")
        message = "Target is not enabled";
      else if (reply.payload == "$error93-")
        message = "Another command is busy";
      else if (reply.payload == "$error94-")
        message = "Storage error";
      else if (reply.payload == "$error95-")
        message = "Radio unavailable";
    }
  screenActionPending = !failed && engine->busy();
  if (screenActionPending)
    screenModel.feedback("Sending request...");
  else
    screenModel.feedback(message, true);
}
void serviceScreen(bool force = false) {
  if (!screenReady || !engine)
    return;
  const uint32_t now = millis();
  if (now - lastTouchPoll >= 10) {
    lastTouchPoll = now;
    // CoreS3 touch is I2C, explicitly not shared with LCD SPI in the pinned
    // M5GFX board definition. Poll only touch, not unrelated accessory drivers.
    M5.Touch.update(now);
    unsigned fingers = 0;
    int x = touchX, y = touchY;
    uint8_t id = touchId;
    for (size_t i = 0; i < M5.Touch.getCount(); ++i) {
      const auto& detail = M5.Touch.getDetail(i);
      if (detail.isPressed()) {
        ++fingers;
        x = detail.x;
        y = detail.y;
        id = detail.id;
      }
    }
    if (fingers > 1 || (fingers == 1 && touchActive && id != touchId)) {
      screenModel.cancelTouch();
      touchBlocked = true;
      touchActive = false;
    } else if (touchBlocked) {
      if (!fingers) {
        screenModel.touch(false, touchX, touchY, engine->state(), screenRuntime());
        touchBlocked = false;
      }
    } else if (fingers == 1) {
      touchX = x;
      touchY = y;
      touchId = id;
      touchActive = true;
      screenModel.touch(true, x, y, engine->state(), screenRuntime());
    } else {
      const bool released = touchActive;
      touchActive = false;
      // Idle samples also clear a cancellation barrier created by an inventory
      // update while no finger was down. Only an observed release may dispatch.
      auto command = screenModel.touch(false, touchX, touchY, engine->state(), screenRuntime());
      if (released)
        screenCommand(command);
    }
  }
  if (GATEWAY_RF_ENABLED && engine->busy())
    return;
  if (!force && now - lastScreenDraw < 100)
    return;
  auto view = screenModel.view(engine->state(), screenRuntime());
  if (force || !screenDrawn || !(view == lastScreenView))
    drawScreen(view);
}
void serialReply(const char* value) {
  Serial.println(value);
}
void serviceSerial() {
  for (unsigned count = 0; Serial.available() && count < 256; ++count) {
    char ch = char(Serial.read());
    if (ch == '\r')
      continue;
    if (ch != '\n') {
      if (serialOverflow)
        continue;
      if (serialInput.size() < 131080)
        serialInput += ch;
      else {
        serialInput.clear();
        serialOverflow = true;
        serialReply("error: serial command too long");
      }
      continue;
    }
    if (serialOverflow) {
      serialOverflow = false;
      continue;
    }
    std::string line = std::move(serialInput);
    serialInput.clear();
    if (line == "status") {
      Serial.printf("storage=%s network=%s mode=%s busy=%u rooms=%u shades=%u\n",
                    storageHealthy ? "ok" : "FAULT", networkStarted ? "up" : "down",
                    GATEWAY_RF_ENABLED ? "radio" : "simulation", engine->busy(),
                    unsigned(engine->state().rooms.size()),
                    unsigned(engine->state().shades.size()));
    } else if (line == "export") {
      auto data = platinum::encodeState(engine->state());
      for (unsigned char b : data)
        Serial.printf("%02x", b);
      Serial.println();
    } else if (line.rfind("import ", 0) == 0) {
      auto hex = line.substr(7);
      std::string bytes;
      bool valid = hex.size() % 2 == 0 && hex.size() <= 131072;
      auto nibble = [](char c) -> int {
        if (c >= '0' && c <= '9')
          return c - '0';
        if (c >= 'a' && c <= 'f')
          return c - 'a' + 10;
        if (c >= 'A' && c <= 'F')
          return c - 'A' + 10;
        return -1;
      };
      for (size_t i = 0; valid && i < hex.size(); i += 2) {
        int a = nibble(hex[i]), b = nibble(hex[i + 1]);
        if (a < 0 || b < 0)
          valid = false;
        else
          bytes += char(a * 16 + b);
      }
      platinum::State state;
      serialReply(valid && platinum::decodeState(bytes, state) && engine->replace(state)
                      ? "ok"
                      : "error: invalid state, storage fault, or busy");
    } else if (line.rfind("grant ", 0) == 0) {
      unsigned shade = 0, features = 0;
      char tail;
      bool ok =
          sscanf(line.c_str(), "grant %u %u %c", &shade, &features, &tail) == 2 && shade < 100;
      auto state = engine->state();
      bool found = false;
      for (auto& s : state.shades)
        if (s.id == shade) {
          s.enabled_features = features;
          found = true;
        }
      serialReply(ok && found && engine->replace(state) ? "ok" : "error: invalid grant or busy");
    } else if (line.rfind("services ", 0) == 0) {
      unsigned tcp = 0, api = 0, page = 0;
      char tail;
      bool ok = sscanf(line.c_str(), "services %u %u %u %c", &tcp, &api, &page, &tail) == 3 &&
                tcp <= 1 && api <= 1 && page <= 1;
      serialReply(ok && saveServices({bool(tcp), bool(api), bool(page)})
                      ? "ok"
                      : "error: invalid services or persistence failure");
    } else if (line.rfind("bind ", 0) == 0) {
      unsigned shade = 0, identity = 0, slot = 0;
      char tail;
      bool ok = sscanf(line.c_str(), "bind %u %x %u %c", &shade, &identity, &slot, &tail) == 3 &&
                shade < engine->state().shades.size() && identity > 0 && identity <= 65535 &&
                slot >= 1 && slot <= 8;
      auto state = engine->state();
      if (ok) {
        auto room = state.shades[shade].room;
        state.rooms[room].rf_id = identity;
        state.shades[shade].slot = slot;
        for (auto& sh : state.shades)
          if (sh.room == room)
            sh.enabled_features = 0;
      }
      serialReply(ok && engine->replace(state) ? "ok: room grants revoked"
                                               : "error: invalid binding or busy");
    } else if (line.rfind("sequence ", 0) == 0) {
      unsigned value = 0;
      char tail;
      bool ok = sscanf(line.c_str(), "sequence %u %c", &value, &tail) == 1 && value <= 65535 &&
                !engine->busy();
      Preferences seq;
      if (ok) {
        bool opened = seq.begin("platinum-seq", false);
        platinum::radio::SequenceStore store(sequenceHooks(seq, opened));
        ok = store.initialize(uint16_t(value));
        if (ok)
          sequenceReady = true;
        seq.end();
      }
      serialReply(ok ? "ok: initial ordinal committed"
                     : "error: existing sequence, invalid value, storage fault, or busy");
    } else
      serialReply(
          "commands: status | export | import HEX | bind SHADE ROOM_HEX SLOT | grant SHADE "
          "FEATURE_BITMASK | sequence NEXT_UNUSED | services TCP HTTP WEB");
  }
}
// Ethernet 2.0.2 silently clamps oversized writes to its socket buffer.
// Offer at most 512 bytes, and never wait on an unwritable peer in the main task.
size_t netWrite(NetClient& client, const uint8_t* bytes, size_t size) {
  size = std::min(size_t(512), size);
#if GATEWAY_NETWORK_WIFI
  int sent = ::send(client.fd(), bytes, size, MSG_DONTWAIT);
  if (sent < 0) {
    if (errno != EAGAIN && errno != EWOULDBLOCK && errno != EINTR)
      client.stop();
    return 0;
  }
  return size_t(sent);
#else
  if (client.availableForWrite() < int(size))
    return 0;
  return client.write(bytes, size);
#endif
}
void serviceLan() {
  auto incoming = lan.accept();
  if (incoming) {
    bool taken = false;
    if (allowed(incoming.remoteIP()))
      for (unsigned i = 0; i < ClientCount; ++i)
        if (!peers[i].client.connected()) {
          peers[i].client.stop();
          peers[i].client = incoming;
          peers[i].session = {};
          peers[i].output = std::to_string(i + 1) + " HunterDouglas Shade Controller\n\r";
          peers[i].touched = millis();
          peers[i].fragmentSince = 0;
          peers[i].outputProgress = millis();
          taken = true;
          break;
        }
    if (!taken)
      incoming.stop();
  }
  for (unsigned i = 0; i < ClientCount; ++i) {
    auto& p = peers[i];
    if (!p.client)
      continue;
    if (millis() - p.touched > 300000 || (p.fragmentSince && millis() - p.fragmentSince > 10000)) {
      p.client.stop();
      continue;
    }
    std::string input;
    for (unsigned n = 0; p.client.available() && n < 256; ++n)
      input += char(p.client.read());
    if (!input.empty()) {
      p.touched = millis();
      queueRecords(engine->feed(p.session, input), i);
      if (p.session.pending.empty())
        p.fragmentSince = 0;
      else if (!p.fragmentSince)
        p.fragmentSince = millis();
      if (p.session.closed) {
        p.client.stop();
        continue;
      }
    }
    if (!p.output.empty()) {
      size_t written =
          netWrite(p.client, reinterpret_cast<const uint8_t*>(p.output.data()), p.output.size());
      if (written) {
        p.output.erase(0, written);
        p.outputProgress = millis();
      } else if (millis() - p.outputProgress > 5000)
        p.client.stop();
    } else {
      p.outputProgress = millis();
    }
  }
}
void serviceDiscovery() {
  int size = udp.parsePacket();
  if (!size)
    return;
  uint8_t data[576];
  int got = udp.read(data, sizeof(data));
  IPAddress remote = udp.remoteIP();
  uint16_t port = udp.remotePort();
  if (size != got || !allowed(remote))
    return;
  if (millis() - discoveryWindow >= 1000) {
    discoveryWindow = millis();
    discoveryReplies = 0;
  }
  if (discoveryReplies >= 20)
    return;
  auto ip = address();
  auto reply = platinum::discoveryResponse(data, size, {ip[0], ip[1], ip[2], ip[3]});
  if (!reply.empty()) {
    ++discoveryReplies;
    udp.beginPacket(remote, port);
    udp.write(reply.data(), reply.size());
    udp.endPacket();
  }
}
void queueHttp(int code, const char* type, const char* body, size_t length, bool html = false) {
  char header[768];
  int count = snprintf(
      header, sizeof(header),
      "HTTP/1.1 %d %s\r\nContent-Type: %s\r\nContent-Length: %u\r\nCache-Control: "
      "no-store\r\nX-Content-Type-Options: nosniff\r\n%sConnection: close\r\n\r\n",
      code, code == 200 ? "OK" : "Error", type, unsigned(length),
      html ? "Content-Security-Policy: default-src 'self'; script-src 'unsafe-inline'; style-src "
             "'unsafe-inline'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'\r\n"
           : "");
  if (count < 0 || size_t(count) >= sizeof(header) || length > 131072 - size_t(count)) {
    web.client.stop();
    web.output.clear();
    web.input.clear();
    return;
  }
  std::string bytes(header, size_t(count));
  bytes.append(body, length);
  if (!web.output.assign(std::move(bytes)))
    web.client.stop();
  web.input.clear();
  web.start = millis();
}
void httpReply(int code, const String& body) {
  queueHttp(code, "application/json", body.c_str(), body.length());
}
void addServices(JsonObject object) {
  object["tcp522"] = services.tcp522;
  object["http"] = services.http;
  object["web"] = services.web;
}
void addStatus(JsonDocument& doc) {
  doc["storage_ok"] = storageHealthy;
  doc["busy"] = engine->busy();
  doc["backend"] = GATEWAY_RF_ENABLED ? "experimental-radio" : "simulated";
  doc["delivery"] = "unverified";
  doc["full_compatibility"] = false;
  addServices(doc["services"].to<JsonObject>());
  doc["operation"]["id"] = operation.id;
  doc["operation"]["status"] = operation.status;
}
void processHttp(const platinum::http::Request& req) {
  const std::string request = req.method + " " + req.path + " HTTP/1.1";
  const std::string expected = strlen(GATEWAY_HTTP_HOST)
                                   ? GATEWAY_HTTP_HOST
                                   : std::string(address().toString().c_str()) + ":8077";
  const auto host = req.header("host"), origin = req.header("origin");
  if (host != expected || (!origin.empty() && origin != "http://" + expected)) {
    httpReply(403, "{\"error\":\"host or origin rejected\"}");
    return;
  }
  if (req.method == "GET" && req.path == "/" && services.web) {
    queueHttp(200, "text/html; charset=utf-8", platinum::web::Page, strlen(platinum::web::Page),
              true);
    return;
  }
  if (req.method == "GET" && req.path == "/health") {
    JsonDocument doc;
    addStatus(doc);
    String out;
    serializeJson(doc, out);
    httpReply(200, out);
    return;
  }
  if (!platinum::http::authorizedBearer(GATEWAY_API_TOKEN, req.header("authorization"))) {
    httpReply(401, "{\"error\":\"unauthorized\"}");
    return;
  }
  if (req.method == "GET") {
    JsonDocument doc;
    if (req.path == "/api/settings")
      addServices(doc.to<JsonObject>());
    else if (req.path == "/api/status")
      addStatus(doc);
    else if (req.path == "/api/inventory") {
      auto records = doc["records"].to<JsonArray>();
      for (const auto& r : engine->snapshot())
        records.add(r.payload);
    } else if (req.path == "/api/shades") {
      addStatus(doc);
      auto shades = doc["shades"].to<JsonArray>();
      for (const auto& shade : engine->state().shades) {
        auto item = shades.add<JsonObject>();
        const auto& room = engine->state().rooms[shade.room];
        item["id"] = shade.id;
        item["room_id"] = shade.room;
        item["room"] = room.name;
        item["name"] = shade.name;
        item["features"] = shade.enabled_features;
        item["enabled"] = bool(shade.enabled_features & (1u << 4));
        item["position"] = nullptr;
        item["observed_position"] = nullptr;
        for (const auto& pos : shade.requested)
          if (pos.feature == 4)
            item["position"] = pos.value;
      }
    } else if (req.path == "/api/rooms") {
      auto rooms = doc["rooms"].to<JsonArray>();
      for (const auto& room : engine->state().rooms) {
        auto item = rooms.add<JsonObject>();
        item["id"] = room.id;
        item["name"] = room.name;
        item["product"] = room.product;
      }
    } else if (req.path == "/api/scenes") {
      auto scenes = doc["scenes"].to<JsonArray>();
      for (const auto& scene : engine->state().scenes) {
        auto item = scenes.add<JsonObject>();
        item["id"] = scene.id;
        item["name"] = scene.name;
        auto shades = item["shades"].to<JsonArray>();
        for (auto id : scene.shades)
          shades.add(id);
      }
    } else {
      httpReply(404, "{\"error\":\"not found\"}");
      return;
    }
    String out;
    serializeJson(doc, out);
    httpReply(200, out);
    return;
  }
  if (req.header("content-type") != "application/json") {
    httpReply(415, "{\"error\":\"application/json required\"}");
    return;
  }
  const auto& body = req.body;
  JsonDocument input;
  if (deserializeJson(input, body) || !input.is<JsonObject>()) {
    httpReply(400, "{\"error\":\"invalid JSON\"}");
    return;
  }
  if (req.method == "PATCH" && req.path == "/api/settings") {
    auto candidate = services;
    bool valid = input.size() > 0;
    for (JsonPair entry : input.as<JsonObject>()) {
      const std::string key = entry.key().c_str();
      if (!entry.value().is<bool>()) {
        valid = false;
        break;
      }
      bool value = entry.value().as<bool>();
      if (key == "tcp522")
        candidate.tcp522 = value;
      else if (key == "http")
        candidate.http = value;
      else if (key == "web")
        candidate.web = value;
      else
        valid = false;
    }
    if (!valid) {
      httpReply(400, "{\"error\":\"expected boolean tcp522, http or web settings\"}");
      return;
    }
    if (!saveServices(candidate)) {
      httpReply(503, "{\"error\":\"settings could not be committed\"}");
      return;
    }
    JsonDocument doc;
    addServices(doc.to<JsonObject>());
    String out;
    serializeJson(doc, out);
    httpReply(200, out);
    return;
  }
  std::string command;
  if (request == "POST /api/command HTTP/1.1")
    command = input["command"].as<std::string>();
  else if (request == "POST /api/scenes HTTP/1.1") {
    if (!input["scene"].is<unsigned>() || input["scene"].as<unsigned>() >= 100) {
      httpReply(400, "{\"error\":\"invalid scene\"}");
      return;
    }
    command = "$inm" + std::to_string(input["scene"].as<unsigned>()) + "-";
  } else if (request == "POST /api/positions HTTP/1.1" || request == "POST /api/sync HTTP/1.1" ||
             request == "POST /api/jog HTTP/1.1") {
    if (!input["shade"].is<unsigned>() || input["shade"].as<unsigned>() >= 100) {
      httpReply(400, "{\"error\":\"invalid shade\"}");
      return;
    }
    unsigned shade = input["shade"].as<unsigned>();
    char buffer[48];
    if (request == "POST /api/sync HTTP/1.1")
      snprintf(buffer, sizeof(buffer), "$rsc%02u-", shade);
    else if (request == "POST /api/jog HTTP/1.1")
      snprintf(buffer, sizeof(buffer), "$pss%02u-12-000-$rls", shade);
    else {
      if (!input["position"].is<unsigned>() || input["position"].as<unsigned>() > 255) {
        httpReply(400, "{\"error\":\"invalid position\"}");
        return;
      }
      snprintf(buffer, sizeof(buffer), "$pss%02u-04-%03u-$rls", shade,
               input["position"].as<unsigned>());
    }
    command = buffer;
  } else {
    httpReply(404, "{\"error\":\"not found\"}");
    return;
  }
  if (command.empty() || command.size() > 1024) {
    httpReply(400, "{\"error\":\"invalid command\"}");
    return;
  }
  const auto id = input["request_id"].as<std::string>();
  if (id.size() < 8 || id.size() > 64 ||
      id.find_first_not_of("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_") !=
          std::string::npos) {
    httpReply(
        400,
        "{\"error\":\"request_id must be 8 to 64 ASCII letters, digits, hyphens or underscores\"}");
    return;
  }
  for (const auto& cached : requestCache)
    if (cached.id == id) {
      if (cached.command != command)
        httpReply(409, "{\"error\":\"request_id already used for another command\"}");
      else
        httpReply(cached.status, cached.response);
      return;
    }
  if (!platinum::validateTransaction(engine->state(), command)) {
    httpReply(409, "{\"error\":\"command invalid, incomplete, or release missing\"}");
    return;
  }
  const bool alreadyBusy = engine->busy();
  platinum::Session session;
  auto replies = engine->feed(session, command);
  queueRecords(replies);
  JsonDocument output;
  auto records = output["records"].to<JsonArray>();
  bool error = false;
  for (const auto& r : replies) {
    records.add(r.payload);
    if (r.payload.rfind("$error", 0) == 0)
      error = true;
  }
  output["request_id"] = id;
  const bool accepted = !alreadyBusy && engine->busy();
  if (accepted) {
    operation.id = id;
    operation.status = "submitted";
  }
  output["operation"]["id"] = operation.id;
  output["operation"]["status"] = operation.status;
  output["delivery"] = "unverified";
  output["status"] = error ? "rejected" : accepted ? "submitted" : "processed";
  output["backend"] = GATEWAY_RF_ENABLED ? "experimental-radio" : "simulated";
  if (!session.pending.empty() || !session.staged.empty()) {
    httpReply(400, "{\"error\":\"command incomplete or release missing\"}");
    return;
  }
  String out;
  serializeJson(output, out);
  size_t entryBytes = id.size() + command.size() + out.length();
  while (!requestCache.empty() && (requestCache.size() >= 16 || cacheBytes + entryBytes > 65536)) {
    const auto& oldest = requestCache.front();
    cacheBytes -= oldest.id.size() + oldest.command.size() + oldest.response.length();
    requestCache.erase(requestCache.begin());
  }
  if (entryBytes <= 65536) {
    requestCache.push_back({id, command, out, error ? 409 : 200});
    cacheBytes += entryBytes;
  }
  httpReply(error ? 409 : 200, out);
}
void serviceHttp() {
  if (web.output.pending()) {
    if (!web.client.connected() || millis() - web.start > 5000) {
      web.client.stop();
      web.output.clear();
      return;
    }
    auto result = web.output.pump(
        [](const uint8_t* bytes, size_t size) { return netWrite(web.client, bytes, size); });
    if (result != platinum::http::PumpResult::Pending) {
      web.client.stop();
      web.output.clear();
    }
    return;
  }
  if (!services.http)
    return;
  auto incoming = http.accept();
  if (incoming) {
    if (!web.client && allowed(incoming.remoteIP())) {
      web.client = incoming;
      web.input.clear();
      web.start = millis();
    } else
      incoming.stop();
  }
  if (!web.client)
    return;
  if (!web.client.connected() && !web.client.available()) {
    web.client.stop();
    web.input.clear();
    return;
  }
  if (millis() - web.start > 5000) {
    httpReply(408, "{\"error\":\"timeout\"}");
    return;
  }
  for (unsigned n = 0; web.client.available() && n < 512; ++n)
    web.input += char(web.client.read());
  platinum::http::Request request;
  switch (platinum::http::parse(web.input, request)) {
    case platinum::http::ParseResult::Incomplete:
      return;
    case platinum::http::ParseResult::Invalid:
      httpReply(400, "{\"error\":\"invalid HTTP request\"}");
      return;
    case platinum::http::ParseResult::TooLarge:
      httpReply(413, "{\"error\":\"request too large\"}");
      return;
    case platinum::http::ParseResult::Complete:
      processHttp(request);
      return;
  }
}
void stopServer(NetServer& server, uint16_t port) {
#if GATEWAY_NETWORK_WIFI
  server.end();
#else
  (void)server;
  for (uint8_t i = 0; i < MAX_SOCK_NUM; ++i)
    if (EthernetServer::server_port[i] == port) {
      EthernetClient socket(i);
      socket.stop();
      EthernetServer::server_port[i] = 0;
    }
#endif
}
void applyServices() {
  if (!networkBusReady())
    return;
  bool enableLan = networkStarted && storageHealthy && services.tcp522;
  bool enableHttp = networkStarted && storageHealthy && services.http;
  if (enableLan != lanRunning) {
    if (enableLan) {
      lan.begin();
      udp.begin(137);
    } else {
      for (auto& p : peers) {
        p.client.stop();
        p.session = {};
        p.output.clear();
      }
      stopServer(lan, 522);
      udp.stop();
    }
    lanRunning = enableLan;
  }
  if (enableHttp != httpRunning) {
    // Finish the settings response before closing HTTP after its disable switch.
    if (!enableHttp && networkStarted && web.output.pending())
      return;
    if (enableHttp)
      http.begin();
    else {
      web.client.stop();
      web.input.clear();
      web.output.clear();
      stopServer(http, 8077);
    }
    httpRunning = enableHttp;
  }
}
void finishOperation(bool ok) {
  if (screenActionPending) {
    screenModel.feedback(ok ? "Request accepted" : "Command failed; check gateway", !ok);
    screenActionPending = false;
  }
  operation.status = ok ? (GATEWAY_RF_ENABLED ? "completed_unverified" : "simulated") : "failed";
  for (auto& item : requestCache)
    if (!operation.id.empty() && item.id == operation.id) {
      JsonDocument doc;
      if (deserializeJson(doc, item.response))
        continue;
      cacheBytes -= item.response.length();
      doc["status"] = operation.status;
      doc["operation"]["status"] = operation.status;
      item.response = "";
      serializeJson(doc, item.response);
      item.status = ok ? 200 : 502;
      cacheBytes += item.response.length();
    }
  queueRecords(engine->complete(ok));
}
void startNetwork() {
  if (!networkBusReady())
    return;
#if GATEWAY_NETWORK_WIFI
  if (networkStarted && WiFi.status() != WL_CONNECTED) {
    for (auto& p : peers) {
      p.client.stop();
      p.session = {};
      p.output.clear();
    }
    networkStarted = false;
    applyServices();
  }
#else
  if (!engine->busy() && !touchActive && Ethernet.linkStatus() != LinkOFF &&
      millis() - lastDhcp > 30000) {
    lastDhcp = millis();
    if (uint32_t(Ethernet.localIP()) == 0) {
      uint8_t mac[6];
      esp_read_mac(mac, ESP_MAC_WIFI_STA);
      mac[0] = (mac[0] | 2) & 0xfe;
      Ethernet.begin(mac, 1000, 250);
      Ethernet.setRetransmissionTimeout(200);
      Ethernet.setRetransmissionCount(1);
    } else
      Ethernet.maintain();
  }
#endif
  if (networkStarted || !storageHealthy || !localNetworkConfig())
    return;
#if GATEWAY_NETWORK_WIFI
  if (WiFi.status() != WL_CONNECTED)
    return;
#else
  if (Ethernet.hardwareStatus() == EthernetNoHardware || uint32_t(Ethernet.localIP()) == 0)
    return;
#endif
  networkStarted = true;
  applyServices();
  serialReply("network ready; configured services enabled");
}
}  // namespace
void setup() {
  // Hold the radio pins passive until the carrier rail is present.
  for (int pin : {5, 6, 8, 10, 17, 18})
    pinMode(pin, INPUT);
  pinMode(9, OUTPUT);
  digitalWrite(9, HIGH);
  pinMode(7, OUTPUT);
  digitalWrite(7, LOW);
  auto config = M5.config();
  config.clear_display = false;
  config.internal_spk = false;
  config.internal_mic = false;
  config.external_spk = false;
  config.external_display_value = 0;
  config.output_power = true;
  M5.begin(config);
  M5.Power.setUsbOutput(false);
  M5.Power.setExtOutput(true);
  const bool busPowered = M5.Power.getExtOutput();
  if (GATEWAY_SCREEN_ENABLED) {
    screenReady = displayBus.begin(!GATEWAY_NETWORK_WIFI);
    if (screenReady && displayBus.acquireDisplay()) {
      // CoreS3's panel has offset_rotation=3; logical rotation 1 is 320x240.
      M5.Display.setRotation(1);
      M5.Display.wakeup();
      M5.Display.setBrightness(128);
      screenReady = M5.Display.width() == 320 && M5.Display.height() == 240 && M5.Touch.isEnabled();
      displayBus.releaseDisplay();
    } else
      screenReady = false;
    if (screenReady) {
      screenSprite.setColorDepth(16);
      screenSprite.setPsram(true);
      screenReady = screenSprite.createSprite(320, 240) != nullptr;
    }
  } else {
    M5.Display.sleep();
    M5.Display.releaseBus();
    pinMode(3, OUTPUT);
    digitalWrite(3, HIGH);
    pinMode(35, INPUT);
  }
  pinMode(4, OUTPUT);
  digitalWrite(4, HIGH);
  Serial.begin(115200);
  if (GATEWAY_SCREEN_ENABLED && !screenReady)
    serialReply(
        "Touchscreen unavailable: check board/touch, PSRAM framebuffer and bus initialization");
  delay(50);  // Provisional rail settle; measure on first article.
  platinum::radio::Policy policy;
  policy.enabled = GATEWAY_RF_ENABLED;
  policy.qualified = GATEWAY_RF_QUALIFIED;
  if (GATEWAY_RF_ENABLED && busPowered)
    radioReady = radio.begin(policy) == platinum::radio::ResultCode::Ready;
  storageHealthy = database.begin("platinum-db", false);
  if (storageHealthy && database.isKey("services")) {
    uint8_t bits = database.getUChar("services", 255);
    if (bits > 7)
      storageHealthy = false;
    else
      services = {bool(bits & 1), bool(bits & 2), bool(bits & 4)};
  }
  platinum::State state;
  if (storageHealthy && database.isKey("state")) {
    size_t size = database.getBytesLength("state");
    if (size == 0 || size > 65536)
      storageHealthy = false;
    else {
      std::string bytes(size, '\0');
      storageHealthy = database.getBytes("state", &bytes[0], size) == size &&
                       platinum::decodeState(bytes, state);
    }
  } else if (storageHealthy) {
    uint8_t mac[6];
    esp_read_mac(mac, ESP_MAC_WIFI_STA);
    char text[13];
    snprintf(text, sizeof(text), "%02X%02X%02X%02X%02X%02X", mac[0], mac[1], mac[2], mac[3], mac[4],
             mac[5]);
    state.mac = text;
    storageHealthy = saveState(state);
  }
  // No stale wall clock scheduling after a reboot. The app must set date/time.
  state.clock.date_valid = false;
  state.clock.time_valid = false;
  platinum::Hooks hooks;
  hooks.persist = saveState;
  hooks.submit = submit;
  hooks.random16 = []() { return uint16_t(esp_random()); };
  hooks.cancel = []() { abortRadio = true; };
  engine.reset(new platinum::Engine(std::move(state), hooks));
  jobs = xQueueCreate(1, sizeof(std::vector<platinum::RadioCommand>*));
  results = xQueueCreate(1, sizeof(bool));
  if (!jobs || !results ||
      xTaskCreatePinnedToCore(radioTask, "gateway-radio", 6144, nullptr, 2, nullptr, 0) != pdPASS)
    storageHealthy = false;
  serviceScreen(true);
#if GATEWAY_NETWORK_WIFI
  WiFi.mode(WIFI_STA);
  if (strlen(GATEWAY_WIFI_SSID))
    WiFi.begin(GATEWAY_WIFI_SSID, GATEWAY_WIFI_PASSWORD);
#else
  if (!GATEWAY_SCREEN_ENABLED)
    SPI.begin(36, 35, 37, -1);
  if (!networkBusReady()) {
    serialReply("display/network bus initialization failed");
    return;
  }
  Ethernet.init(9);
  digitalWrite(7, HIGH);
  delay(100);
  uint8_t mac[6];
  esp_read_mac(mac, ESP_MAC_WIFI_STA);
  mac[0] = (mac[0] | 2) & 0xfe;
  // Bring up the chip without waiting for a cable or DHCP server. Discovery
  // and listeners remain closed until the main loop obtains a real lease.
  const IPAddress none(0, 0, 0, 0);
  Ethernet.begin(mac, none, none, none, none);
  lastDhcp = millis() - 30001u;
  Ethernet.setRetransmissionTimeout(200);
  Ethernet.setRetransmissionCount(1);
#endif
  lastTick = millis();
  serialReply("Platinum gateway ready; USB command: status. RF delivery remains unverified.");
}
void loop() {
  serviceSerial();
  bool completed = false;
  if (results && xQueueReceive(results, &completed, 0) == pdTRUE)
    finishOperation(completed);
  uint32_t now = millis();
  if (now - lastTick >= 1000) {
    uint32_t seconds = (now - lastTick) / 1000;
    lastTick += seconds * 1000;
    queueRecords(engine->tick(seconds));
  }
  if (now - lastNetworkTry >= 1000) {
    lastNetworkTry = now;
    startNetwork();
  }
  applyServices();
  if (lanRunning && networkBusReady()) {
    serviceLan();
    serviceDiscovery();
  }
  if (httpRunning && networkBusReady())
    serviceHttp();
  serviceScreen();
  delay(1);
}
