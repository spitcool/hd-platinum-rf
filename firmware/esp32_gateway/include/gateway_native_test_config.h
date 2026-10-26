// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#pragma once

// Optional installation network/token settings remain private. Without them,
// USB provisioning and bounded radio tests work with network clients disabled.
#if __has_include("gateway_config.h")
#include "gateway_config.h"
#endif

#undef GATEWAY_RF_ENABLED
#undef GATEWAY_RF_NATIVE
#undef GATEWAY_RF_BENCH
#undef GATEWAY_RF_QUALIFIED
#undef GATEWAY_RF_NATIVE_QUALIFIED_FEATURES
#define GATEWAY_RF_ENABLED true
#define GATEWAY_RF_NATIVE true
#define GATEWAY_RF_BENCH true
#define GATEWAY_RF_QUALIFIED false
#define GATEWAY_RF_NATIVE_QUALIFIED_FEATURES 0u
// No transmission is admitted at boot, including from saved simulation grants.
// USB rf-test FEATURE_BITMASK arms only supported features for at most 60 s.
