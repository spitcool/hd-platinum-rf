// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <limits>
#include <string>

#include "../../include/serial_arguments.h"

using platinum::serial::unsignedArguments;

int main() {
  std::array<uint32_t, 1> one{99};
  for (const auto& input : {"rf-test 0", "rf-test 0000", "rf-test\t000 \t"}) {
    assert(unsignedArguments(input, "rf-test", one));
    assert(one[0] == 0);
  }
  assert(unsignedArguments("rf-test 16", "rf-test", one) && one[0] == 16);
  assert(unsignedArguments("n 2147483647", "n", one) && one[0] == 2147483647u);
  assert(unsignedArguments("n 2147483648", "n", one) && one[0] == 2147483648u);
  assert(unsignedArguments("n 0004294967295", "n", one));
  assert(one[0] == std::numeric_limits<uint32_t>::max());

  // scanf("%u") can wrap these malformed values into permitted feature bit16.
  for (const auto& input : {
      "rf-test -4294967280", "rf-test 4294967312", "rf-test 4294967296",
      "rf-test 999999999999999999999999999999999999", "rf-test -1", "rf-test +16",
      "rf-test 0x10", "rf-test 16.0", "rf-test 1e1", "rf-test 16junk",
      "rf-test16", "rf-tests 16", "rf-test", "rf-test \t", "rf-test 16 0",
      "rf-test 16\n", "rf-test 16\r", " rf-test 16", "RF-TEST 16"}) {
    one[0] = 99;
    assert(!unsignedArguments(input, "rf-test", one));
    assert(one[0] == 99);
  }
  const std::string embedded_nul("rf-test 16\0junk", 15);
  assert(!unsignedArguments(embedded_nul, "rf-test", one));
  assert(!unsignedArguments("16", "", one));
  assert(!unsignedArguments("rf test 16", "rf test", one));

  std::array<uint32_t, 4> control{9, 9, 9, 9};
  assert(unsignedArguments("control\t00  18\t3 0255 \t", "control", control));
  assert((control == std::array<uint32_t, 4>{0, 18, 3, 255}));
  for (const auto& input : {"control 0 18 3", "control 0 18 3 255 1",
                           "control 0 18 3 -1", "control 0 18 3 4294967296"}) {
    const auto saved = control;
    assert(!unsignedArguments(input, "control", control));
    assert(control == saved);  // Later-field failure cannot partially mutate output.
  }
  std::array<uint32_t, 3> services{};
  assert(unsignedArguments("services 1 0 1", "services", services));
  assert((services == std::array<uint32_t, 3>{1, 0, 1}));
  std::array<uint32_t, 2> grant{};
  assert(unsignedArguments("grant 99 4294967295", "grant", grant));
  assert(grant[0] == 99 && grant[1] == std::numeric_limits<uint32_t>::max());
  std::array<uint32_t, 0> none{};
  assert(unsignedArguments("status\t ", "status", none));
  assert(!unsignedArguments("status 1", "status", none));
  std::cout << "Strict unsigned serial arguments and overflow regressions passed\n";
}
