// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

// Fictional installation for the local ESP32 instruction emulator. Does not
// read the physical installation's private gateway_config.h.
#define GATEWAY_WIFI_SSID "Wokwi-GUEST"
#define GATEWAY_WIFI_PASSWORD ""
#define GATEWAY_CLIENT_NETWORK "10.0.2.0"
#define GATEWAY_CLIENT_MASK "255.255.255.0"
#define GATEWAY_HTTP_HOST "127.0.0.1:18080"
#define GATEWAY_API_TOKEN "wokwi-local-development-token-0001"
#define GATEWAY_RF_ENABLED false
#define GATEWAY_RF_QUALIFIED false
