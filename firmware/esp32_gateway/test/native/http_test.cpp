// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include <cassert>
#include <cstdint>
#include <iostream>
#include <string>

#include "http_protocol.h"
using namespace platinum::http;
namespace {
ParseResult result(const std::string& input) {
  Request r;
  return parse(input, r);
}
std::string post(const std::string& body, const std::string& method = "POST") {
  return method +
         " /api/positions HTTP/1.1\r\nHost: 192.0.2.1:8077\r\nContent-Type: "
         "application/json\r\nContent-Length: " +
         std::to_string(body.size()) + "\r\n\r\n" + body;
}
void fragments() {
  auto wire = post("{\"shade\":0,\"position\":128}");
  for (size_t split = 0; split < wire.size(); ++split) {
    Request r;
    r.path = "unchanged";
    assert(parse(wire.substr(0, split), r) == ParseResult::Incomplete);
    assert(r.path == "unchanged");
    assert(parse(wire, r) == ParseResult::Complete);
    assert(r.path == "/api/positions" && r.method == "POST");
    assert(r.header("HOST") == "192.0.2.1:8077");
    assert(r.headerCount("Content-Length") == 1);
    assert(r.body == "{\"shade\":0,\"position\":128}");
  }
  assert(result(post("{}", "PATCH")) == ParseResult::Complete);
  assert(result("GET /health HTTP/1.1\r\nhOsT:\t192.0.2.1:8077 \t\r\n\r\n") ==
         ParseResult::Complete);
  assert(result("GET / HTTP/1.1\r\nHost: host\r\nAccept: a\r\nAccept: b\r\n\r\n") ==
         ParseResult::Complete);
}
void malformed() {
  const char* bad[] = {
      "GET / HTTP/1.1\r\n\r\n",
      "GET / HTTP/1.0\r\nHost: host\r\n\r\n",
      "GET / HTTP/1.1\nHost: host\n\n",
      "GET / HTTP/1.1\rHost: host\r\n\r\n",
      "GET / HTTP/1.1\r\nHost: host\r\nHOST: another\r\n\r\n",
      "GET / HTTP/1.1\r\nHost: host\r\nAuthorization: a\r\nAuthorization: b\r\n\r\n",
      "GET / HTTP/1.1\r\nHost: host\r\nContent-Type: a\r\nContent-Type: b\r\n\r\n",
      "GET / HTTP/1.1\r\nHost: host\r\nOrigin: a\r\nOrigin: b\r\n\r\n",
      "GET / HTTP/1.1\r\nHost: \r\n\r\n",
      "GET / HTTP/1.1\r\nHost: user@host\r\n\r\n",
      "GET / HTTP/1.1\r\n Host: host\r\n\r\n",
      "GET / HTTP/1.1\r\nHost : host\r\n\r\n",
      "GET / HTTP/1.1\r\nHost: host\r\nTransfer-Encoding: identity\r\n\r\n",
      "GET / HTTP/1.1\r\nHost: host\r\nContent-Length: 1\r\n\r\nx",
      "POST / HTTP/1.1\r\nHost: host\r\n\r\n",
      "PATCH / HTTP/1.1\r\nHost: host\r\n\r\n",
      "POST / HTTP/1.1\r\nHost: host\r\nContent-Length: 0\r\nContent-Length: 0\r\n\r\n",
      "POST / HTTP/1.1\r\nHost: host\r\nContent-Length: +0\r\n\r\n",
      "POST / HTTP/1.1\r\nHost: host\r\nContent-Length: -1\r\n\r\n",
      "POST / HTTP/1.1\r\nHost: host\r\nContent-Length: 0,0\r\n\r\n",
      "POST / HTTP/1.1\r\nHost: host\r\nContent-Length: \r\n\r\n",
      "GET //bad path HTTP/1.1\r\nHost: host\r\n\r\n",
      "GET /#fragment HTTP/1.1\r\nHost: host\r\n\r\n",
      "GET http://host/ HTTP/1.1\r\nHost: host\r\n\r\n",
      "DELETE / HTTP/1.1\r\nHost: host\r\n\r\n",
      "GET / HTTP/1.1\r\nHost: host\r\n\r\nGET / HTTP/1.1\r\nHost: host\r\n\r\n"};
  for (const char* request : bad)
    assert(result(request) == ParseResult::Invalid);
  auto nul = post(std::string("a\0b", 3));
  assert(result(nul) == ParseResult::Invalid);
  auto ctl = post(std::string("a\x01", 2));
  assert(result(ctl) == ParseResult::Invalid);
  assert(result(post("{}") + "x") == ParseResult::Invalid);
}
void limits() {
  assert(result(post(std::string(MaxBody, ' '))) == ParseResult::Complete);
  assert(result(post(std::string(MaxBody + 1, ' '))) == ParseResult::TooLarge);
  assert(result("POST / HTTP/1.1\r\nHost: host\r\nContent-Length: 184467440737095516160\r\n\r\n") ==
         ParseResult::TooLarge);
  assert(result(std::string(MaxHeaders + 1, 'x')) == ParseResult::TooLarge);
  std::string many = "GET / HTTP/1.1\r\nHost: host\r\n";
  for (unsigned i = 0; i < 64; ++i)
    many += "X: a\r\n";
  many += "\r\n";
  assert(result(many) == ParseResult::TooLarge);
  assert(result(std::string(MaxRequest + 1, 'x')) == ParseResult::TooLarge);
}
void auth() {
  const std::string token(32, 'x');
  assert(authorizedBearer(token, "Bearer " + token));
  assert(!authorizedBearer("short", "Bearer short"));
  for (size_t i = 0; i < 39; ++i) {
    auto value = "Bearer " + token;
    value[i] ^= 1;
    assert(!authorizedBearer(token, value));
  }
  assert(!authorizedBearer(token, "Bearer " + token + "x"));
  assert(!authorizedBearer(token, "Bearer " + token.substr(1)));
  assert(!authorizedBearer(token, ""));
}
void fuzz() {
  uint32_t seed = 0x12736589;
  for (unsigned trial = 0; trial < 3000; ++trial) {
    std::string input;
    for (unsigned i = 0; i < trial % 256; ++i) {
      seed = seed * 1664525u + 1013904223u;
      input += char(seed >> 24);
    }
    Request r;
    parse(input, r);
  }
}
}  // namespace
int main() {
  fragments();
  malformed();
  limits();
  auth();
  fuzz();
  std::cout << "HTTP parser tests passed\n";
}
