# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: GPL-2.0-or-later
cmake_minimum_required(VERSION 3.16)
project(platinum_gateway_native LANGUAGES CXX)

if(NOT CMAKE_BUILD_TYPE)
  set(CMAKE_BUILD_TYPE Debug CACHE STRING "Build type" FORCE)
endif()
set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)
option(GATEWAY_SANITIZERS "Enable address and undefined-behavior sanitizers" OFF)

add_library(gateway_native
  lib/gateway_core/gateway_core.cpp
  lib/gateway_core/state_codec.cpp
  lib/gateway_core/discovery.cpp
  lib/gateway_http/http_protocol.cpp
  lib/gateway_radio/gateway_radio.cpp
  lib/gateway_ui/ui_model.cpp
  lib/gateway_ui/ui_renderer.cpp
  lib/gateway_display/display_bus.cpp)
target_include_directories(gateway_native PUBLIC lib/gateway_core lib/gateway_http lib/gateway_radio lib/gateway_ui lib/gateway_display)
if(CMAKE_CXX_COMPILER_ID MATCHES "Clang|GNU")
  target_compile_options(gateway_native PUBLIC -Wall -Wextra -Wpedantic -UNDEBUG)
  if(GATEWAY_SANITIZERS)
    target_compile_options(gateway_native PUBLIC -fsanitize=address,undefined -fno-omit-frame-pointer)
    target_link_options(gateway_native PUBLIC -fsanitize=address,undefined)
  endif()
elseif(MSVC)
  target_compile_options(gateway_native PUBLIC /W4 /UNDEBUG)
endif()

enable_testing()
file(GLOB NATIVE_TESTS CONFIGURE_DEPENDS "test/native/*_test.cpp" "test/native/test_*.cpp")
foreach(TEST_SOURCE IN LISTS NATIVE_TESTS)
  get_filename_component(TEST_NAME "${TEST_SOURCE}" NAME_WE)
  add_executable("${TEST_NAME}" "${TEST_SOURCE}")
  target_link_libraries("${TEST_NAME}" PRIVATE gateway_native)
  add_test(NAME "${TEST_NAME}" COMMAND "${TEST_NAME}")
  set_tests_properties("${TEST_NAME}" PROPERTIES TIMEOUT 30)
endforeach()

# Render synthetic screen examples with the same portable painter used on device.
add_executable(screen_preview tools/preview_screen.cpp)
target_link_libraries(screen_preview PRIVATE gateway_native)

# Persistent local simulator: one tab-delimited request and JSON response per line.
add_executable(gateway_simulator tools/simulator_core.cpp)
target_link_libraries(gateway_simulator PRIVATE gateway_native)

# Generate a binary-codec inventory for provisioning a virtual board over USB.
add_executable(sample_inventory tools/sample_inventory.cpp)
target_link_libraries(sample_inventory PRIVATE gateway_native)
