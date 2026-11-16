// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

// Copy to gateway_config.h (ignored). USB-C power only; no LAN-base DC input.
#define GATEWAY_WIFI_SSID ""
#define GATEWAY_WIFI_PASSWORD ""
// Explicit trusted IPv4 network. A zero mask disables all network clients.
#define GATEWAY_CLIENT_NETWORK "192.168.1.0"
#define GATEWAY_CLIENT_MASK "255.255.255.0"
#define GATEWAY_API_TOKEN ""  // Set to at least 32 random characters.
// Persisted USB/API settings override these initial defaults after first change.
#define GATEWAY_TCP_ENABLED true
#define GATEWAY_HTTP_ENABLED true
#define GATEWAY_WEB_ENABLED true
// Local touchscreen runs independently of TCP/HTTP. Set false for headless operation.
#define GATEWAY_SCREEN_ENABLED true
// Simulation only by default; simulated commands never assert delivery.
#define GATEWAY_RF_ENABLED false
#define GATEWAY_RF_QUALIFIED false
// Native direct-to-shade transport is separate from the original repeater experiment.
#define GATEWAY_RF_NATIVE false
// A native bench build starts disarmed; USB rf-test opens a 60-second window.
#define GATEWAY_RF_BENCH false
// Per-feature physical NiceRF qualification, independent of shade grants.
#define GATEWAY_RF_NATIVE_QUALIFIED_FEATURES 0u
// Optional primary-position bench experiment only: 0 none, 1 wake, 2 command
// control. Positive counts must be multiples of 3, at most 975 with the fixed
// 9000-packet application train. Requires enabled native bench RF and feature 4
// unqualified; no effect on secondary/Jog. See docs/radio-qualification.md.
#define GATEWAY_RF_NATIVE_PREPARATION 0
#define GATEWAY_RF_NATIVE_PREPARATION_FRAMES 0u
// Initial sequence is provisioned via USB serial, never reset on normal boot.
