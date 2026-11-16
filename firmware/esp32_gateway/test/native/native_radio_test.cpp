// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include <algorithm>
#include <array>
#include <cassert>
#include <cstdint>
#include <iostream>
#include <limits>
#include <vector>

#include "gateway_radio.h"

using namespace platinum::radio;

namespace {
Command command(Operation operation = Operation::Position) {
  Command c;
  c.room_id = {0x12, 0x34};  // Fictional identity, not installation data.
  c.mask = 8;
  c.position = 128;
  c.operation = operation;
  c.operation_enabled = true;
  return c;
}
NativeSchedule schedule(uint32_t held = 7500, uint32_t tail = 1500) {
  return {71, 0, held, tail, kNativeSlotHalfUs};
}
Policy bench() {
  Policy p;
  p.enabled = true;
  p.route = Route::Native;
  p.native_position = p.native_jog = p.native_secondary = NativeAccess::Bench;
  return p;
}

// Unlike the older bridge fake, every transfer takes its actual wire time.
// TX_DS becomes visible 180us after CE (130us settle+44us data+6us IRQ),
// not immediately on CE. Retuning/upload during a prior frame is forbidden.
class TimedIo : public Io {
 public:
  std::array<std::array<uint8_t, 5>, 32> regs{};
  std::vector<std::array<uint8_t, 5>> payloads;
  std::vector<uint8_t> channels;
  std::vector<uint64_t> pulses;
  uint64_t time = 0, complete_at = 0;
  uint32_t hz = 1000000, completion_us = 180;
  int corrupt_fast_register = -1;
  uint32_t delay_overshoot = 0;
  bool fast_supported = true, ignore_fast_clock = false;
  bool timed = false, ce = false, transmitting = false;
  bool suppress_completion = false, bad_status = false, bad_fifo = false;
  bool preempt_next_load = false;
  unsigned begins = 0, ends = 0, writes = 0;
  uint8_t status = 0;

  bool begin() override {
    regs[0x17][0] = 0x11;
    return true;
  }
  void end() override { assert(!timed); }
  bool beginTimedBurst(uint32_t clock) override {
    assert(clock == 8000000 && !timed);
    if (!fast_supported)
      return false;
    timed = true;
    hz = ignore_fast_clock ? 1000000 : clock;
    ++begins;
    return true;
  }
  void endTimedBurst() override {
    assert(timed);
    timed = false;
    hz = 1000000;
    ++ends;
  }
  void update() {
    if (transmitting && time >= complete_at && !suppress_completion) {
      transmitting = false;
      status |= 0x20;
      if (!bad_fifo)
        regs[0x17][0] |= 0x10;
    }
  }
  void chipEnable(bool high) override {
    ce = high;
    if (high) {
      assert(timed && !transmitting && !(regs[0x17][0] & 0x10));
      assert(!payloads.empty());
      pulses.push_back(time);
      channels.push_back(regs[5][0]);
      transmitting = true;
      complete_at = time + completion_us;
    }
  }
  uint8_t transfer(uint8_t instruction, const uint8_t* tx, uint8_t* rx, size_t size) override {
    time += ((size + 1) * 8000000 + hz - 1) / hz;
    update();
    const uint8_t returned = bad_status && !pulses.empty() ? 0xff : status;
    if ((instruction & 0xe0) == 0x20) {
      ++writes;
      const uint8_t reg = instruction & 0x1f;
      if (reg == 7)
        status &= ~tx[0];
      else {
        if (reg == 5)
          assert(!transmitting);
        std::copy(tx, tx + size, regs[reg].begin());
        if (reg == 0 && !(tx[0] & 2))
          transmitting = false;
      }
    } else if (instruction < 0x20) {
      std::copy(regs[instruction].begin(), regs[instruction].begin() + size, rx);
      if (timed && instruction == corrupt_fast_register && size)
        rx[0] ^= 1;
    } else if (instruction == 0xa0) {
      assert(!transmitting && size == 5 && (regs[0x17][0] & 0x10));
      std::array<uint8_t, 5> payload{};
      std::copy(tx, tx + size, payload.begin());
      payloads.push_back(payload);
      regs[0x17][0] &= ~0x10;
      if (preempt_next_load) {
        time += 100;
        preempt_next_load = false;
      }
    } else if (instruction == 0xe1) {
      regs[0x17][0] |= 0x10;
    } else if (instruction == 0xe2) {
      regs[0x17][0] |= 1;
    }
    return returned;
  }
  uint32_t micros() override { return static_cast<uint32_t>(time); }
  void delayUs(uint32_t duration) override {
    time += duration + (timed ? delay_overshoot : 0);
    update();
  }
};

uint64_t fingerprint(NativePlan& plan) {
  uint64_t value = 14695981039346656037ULL;
  const auto add = [&](uint8_t byte) { value = (value ^ byte) * 1099511628211ULL; };
  NativeEvent event;
  while (plan.next(event)) {
    for (uint32_t number : {event.ordinal, event.start_half_us})
      for (unsigned shift = 0; shift < 32; shift += 8)
        add(static_cast<uint8_t>(number >> shift));
    add(event.channel);
    add(event.phase == NativePhase::Followup ? 1 : 0);
    for (uint8_t byte : event.payload)
      add(byte);
  }
  return value;
}

void complete_planner_vectors() {
  // FNV-1a over every event's <ordinal:u32le,start_half_us:u32le,channel:u8,
  // phase:u8,payload:5>. Generated independently from the public Python native
  // Jog/primary/secondary planners with fictional1234/mask08/value128 and
  // 7500+1500 frames. This checks all162,000 events, not just first/last bodies.
  struct Vector { Operation op; uint8_t prior, alternate; uint64_t hash; };
  const Vector vectors[] = {
      {Operation::Position, 33, 0, 0xd6ab63f440f8293bULL},
      {Operation::Position, 33, 1, 0xd6ab63f440f8293bULL},
      {Operation::Position, 52, 0, 0x9c18c516c34a7723ULL},
      {Operation::Position, 52, 1, 0x9c18c516c34a7723ULL},
      {Operation::Position, 71, 0, 0x96b601e55a392d1fULL},
      {Operation::Position, 71, 1, 0x96b601e55a392d1fULL},
      {Operation::SecondaryPosition, 33, 0, 0xe3c75f7aca4745b7ULL},
      {Operation::SecondaryPosition, 33, 1, 0xe3c75f7aca4745b7ULL},
      {Operation::SecondaryPosition, 52, 0, 0xc15f8973f3731967ULL},
      {Operation::SecondaryPosition, 52, 1, 0xc15f8973f3731967ULL},
      {Operation::SecondaryPosition, 71, 0, 0xa6369cf5f082b18bULL},
      {Operation::SecondaryPosition, 71, 1, 0xa6369cf5f082b18bULL},
      {Operation::Jog, 33, 0, 0x39e7fb04424bd91cULL},
      {Operation::Jog, 33, 1, 0x2cc743b03d928493ULL},
      {Operation::Jog, 52, 0, 0xc08ffd2492f09598ULL},
      {Operation::Jog, 52, 1, 0x4bacc5f10648ff73ULL},
      {Operation::Jog, 71, 0, 0x7e59539cbbbf34c0ULL},
      {Operation::Jog, 71, 1, 0x23b87ad633d15af7ULL},
  };
  for (const auto& vector : vectors) {
    auto s = schedule();
    s.prior_channel = vector.prior;
    s.prior_alternate = vector.alternate;
    NativePlan plan;
    assert(plan.begin(command(vector.op), s));
    assert(plan.frameCount() == 9000 && plan.durationHalfUs() == 3609000);
    assert(fingerprint(plan) == vector.hash);
    NativeEvent exhausted;
    assert(!plan.next(exhausted));
  }
}

void body_and_phase_boundaries() {
  for (Operation operation : {Operation::Position, Operation::SecondaryPosition}) {
    for (unsigned value = 0; value <= 255; ++value) {
      for (uint8_t mask : {1, 2, 4, 8, 16, 32, 64, 128}) {
        auto c = command(operation);
        c.position = value;
        c.mask = mask;
        NativePlan plan;
        assert(plan.begin(c, schedule(4, 5)));  // Boundary not divisible by3.
        NativeEvent event;
        for (unsigned i = 0; i < 9; ++i) {
          assert(plan.next(event));
          assert(event.payload[0] == 0x12 && event.payload[1] == 0x34);
          assert(event.payload[2] == (i >= 4 ? 0x32 : operation == Operation::Position ? 0x50 : 0x6d));
          assert(event.payload[3] == mask && event.payload[4] == value);
          assert((event.channel == std::array<uint8_t, 3>{33, 52, 71}[i % 3]));
          assert(event.phase == (i < 4 ? NativePhase::Command : NativePhase::Followup));
        }
      }
    }
  }
  for (uint8_t prior : {0, 1}) {
    NativePlan plan;
    auto s = schedule(241, 4);
    s.prior_alternate = prior;
    assert(plan.begin(command(Operation::Jog), s));
    NativeEvent event;
    for (unsigned i = 0; i < 245; ++i) {
      assert(plan.next(event));
      // Independently enumerate repeated120-pulse cycles, accounting for the
      // decrement-before-first-CE offset and the two initial alternation states.
      const unsigned phase = (i + 1 + (prior ? 20 : 0)) % 120;
      const bool alternate = phase < 20;
      assert(event.payload[2] == (i >= 241 ? 0x32 : alternate ? 0x20 : 0x6a));
      assert(event.payload[4] == (i < 241 && alternate ? 0x6a : 1));
    }
  }
}

void preparation_experiments() {
  for (auto mode : {NativePreparation::Wake, NativePreparation::CommandControl}) {
    auto s = schedule(4, 5);
    s.preparation = mode;
    s.preparation_frames = 6;
    NativePlan plan;
    assert(plan.begin(command(), s) && plan.frameCount() == 15);
    NativeEvent e;
    for (unsigned i = 0; i < 15; ++i) {
      assert(plan.next(e));
      const bool wake = i < 6 && mode == NativePreparation::Wake;
      const std::array<uint8_t, 5> body = {0x12, 0x34, uint8_t(wake ? 1 : i < 10 ? 0x50 : 0x32),
                                          uint8_t(wake ? 0 : 8), 0x80};
      assert(e.payload == body && e.ordinal == i && e.start_half_us == i * 401);
      assert(e.channel == (std::array<uint8_t, 3>{33, 52, 71}[i % 3]));
      assert(e.phase == (i < 6 ? (wake ? NativePhase::Wake : NativePhase::CommandControl)
                              : i < 10 ? NativePhase::Command : NativePhase::Followup));
    }
    TimedIo io;
    Radio radio(io);
    assert(radio.begin(bench()) == ResultCode::Ready);
    assert(radio.transmitNative(command(), s).code == ResultCode::BenchSubmitted);
    assert(io.pulses.size() == 15);
    for (unsigned i = 0; i < 15; ++i)
      assert(io.pulses[i] - io.pulses[0] == (i * 401 + 1) / 2);

    auto qualified = bench();
    qualified.native_position = NativeAccess::Qualified;
    TimedIo blocked;
    Radio production(blocked);
    assert(production.begin(qualified) == ResultCode::Ready);
    assert(production.transmitNative(command(), s).code == ResultCode::Unqualified);
    assert(blocked.pulses.empty() && blocked.begins == 0);

    // Revocation during preparation must prevent every position packet.
    TimedIo cancelled;
    Radio cancellation(cancelled);
    assert(cancellation.begin(bench()) == ResultCode::Ready);
    const auto stop = [](void* context) { return !static_cast<TimedIo*>(context)->pulses.empty(); };
    assert(cancellation.transmitNative(command(), s, stop, &cancelled).code == ResultCode::Cancelled);
    assert(cancelled.pulses.size() == 1 && !cancellation.ready());

    assert(!plan.begin(command(Operation::Jog), s));
    assert(!plan.begin(command(Operation::SecondaryPosition), s));
    for (uint32_t count : {0u, 1u, 2u, 4u, std::numeric_limits<uint32_t>::max()}) {
      s.preparation_frames = count;
      assert(!plan.begin(command(), s));
    }
    s = schedule();
    s.preparation = mode;
    s.preparation_frames = 975;
    assert(plan.begin(command(), s) && plan.durationHalfUs() == 3999975);
    s.preparation_frames = 978;
    assert(!plan.begin(command(), s));
  }
  auto s = schedule();
  NativePlan plan;
  s.preparation_frames = 3;
  assert(!plan.begin(command(), s));
  s.preparation = static_cast<NativePreparation>(255);
  assert(!plan.begin(command(), s));
}

void invalid_plans() {
  NativePlan plan;
  NativeEvent event;
  assert(!plan.next(event));
  assert(!plan.begin(command(), NativeSchedule{}));
  for (uint8_t mask : {0, 3, 127, 255}) {
    auto c = command();
    c.mask = mask;
    assert(!plan.begin(c, schedule()));
  }
  for (Operation operation : {Operation::Sync, static_cast<Operation>(255)})
    assert(!plan.begin(command(operation), schedule()));
  for (uint8_t channel : {0, 32, 34, 53, 72, 255}) {
    auto s = schedule();
    s.prior_channel = channel;
    assert(!plan.begin(command(), s));
  }
  for (unsigned variant = 0; variant < 6; ++variant) {
    auto s = schedule();
    if (variant == 0) s.prior_alternate = 2;
    if (variant == 1) s.command_frames = 0;
    if (variant == 2) s.followup_frames = 0;
    if (variant == 3) s.slot_half_us = 400;
    if (variant == 4) s.command_frames = 10000;
    if (variant == 5) s.command_frames = s.followup_frames = std::numeric_limits<uint32_t>::max();
    assert(!plan.begin(command(), s));
    assert(plan.frameCount() == 0 && !plan.next(event));
  }
  assert(plan.begin(command(), schedule(9974, 1)));
  assert(!plan.begin(command(), schedule(9975, 1)));
}

void authorization_and_profiles() {
  TimedIo io;
  Radio radio(io);
  auto p = bench();
  p.native_position = p.native_jog = p.native_secondary = NativeAccess::Disabled;
  p.qualified = true;  // Legacy qualification cannot authorize native RF.
  assert(radio.begin(p) == ResultCode::Ready && io.pulses.empty());
  assert(io.regs[0][0] == 0x0e && io.regs[1][0] == 0 && io.regs[3][0] == 1 &&
         io.regs[4][0] == 0 && io.regs[5][0] == 33 && io.regs[6][0] == 8 &&
         io.regs[0x11][0] == 5 && io.regs[0x1c][0] == 0 && io.regs[0x1d][0] == 0);
  const auto writes = io.writes;
  for (Operation op : {Operation::Position, Operation::Jog, Operation::SecondaryPosition})
    assert(radio.transmitNative(command(op), schedule()).code == ResultCode::Unqualified);
  assert(radio.transmitNative(command(Operation::Sync), schedule()).code == ResultCode::UnsupportedOperation);
  assert(radio.transmit(command(), 7).code == ResultCode::InvalidPolicy);
  assert(io.writes == writes && io.pulses.empty() && io.begins == 0);
  p.native_position = NativeAccess::Bench;
  assert(radio.begin(p) == ResultCode::Ready);
  assert(radio.transmitNative(command(Operation::Jog), schedule()).code == ResultCode::Unqualified);
  auto denied = command();
  denied.operation_enabled = false;
  assert(radio.transmitNative(denied, schedule()).code == ResultCode::OperationDisabled);
  assert(radio.transmitNative(command(), NativeSchedule{}).code == ResultCode::InvalidCommand);
  p.enabled = false;
  assert(radio.begin(p) == ResultCode::Ready);
  assert(radio.transmitNative(command(), schedule()).code == ResultCode::Disabled);
  p.enabled = true;
  p.native_position = static_cast<NativeAccess>(255);
  assert(radio.begin(p) == ResultCode::InvalidPolicy);
  p = bench();
  p.power = 3;
  assert(radio.begin(p) == ResultCode::InvalidPolicy && io.pulses.empty());
  p = bench();
  p.route = Route::BridgeRepeater;
  assert(radio.begin(p) == ResultCode::Ready);
  assert(radio.transmitNative(command(), schedule()).code == ResultCode::InvalidPolicy);
}

void finite_timed_transmission() {
  for (uint64_t initial : {uint64_t{0}, uint64_t{0xfffff000}}) {
    for (Operation op : {Operation::Position, Operation::SecondaryPosition, Operation::Jog}) {
      TimedIo io;
      io.time = initial;
      Radio radio(io);
      auto p = bench();
      assert(radio.begin(p) == ResultCode::Ready);
      const auto result = radio.transmitNative(command(op), schedule());
      assert(result.code == ResultCode::BenchSubmitted && result.frames_submitted == 9000 &&
             result.missing_acks == 0 && result.max_lateness_us == 0);
      assert(io.pulses.size() == 9000 && !io.ce && !io.timed && !io.transmitting);
      assert(io.begins == 1 && io.ends == 1 && radio.ready());
      NativePlan plan;
      assert(plan.begin(command(op), schedule()));
      NativeEvent event;
      for (size_t i = 0; i < io.pulses.size(); ++i) {
        assert(plan.next(event));
        assert(io.payloads[i] == event.payload && io.channels[i] == event.channel);
        assert(io.pulses[i] - io.pulses[0] == (i * 401 + 1) / 2);
      }
      radio.shutdown();
      assert(!radio.ready() && io.regs[0][0] == 0x0c);
    }
  }
  TimedIo io;
  io.completion_us = 185;  // Bound also accommodates possible97-bit framing.
  Radio radio(io);
  auto p = bench();
  p.native_position = NativeAccess::Qualified;
  assert(radio.begin(p) == ResultCode::Ready);
  assert(radio.transmitNative(command(), schedule(4, 5)).code == ResultCode::Submitted);
  assert(io.pulses.size() == 9);
}

void timing_faults_and_cancellation() {
  for (unsigned fault = 0; fault < 8; ++fault) {
    TimedIo io;
    Radio radio(io);
    assert(radio.begin(bench()) == ResultCode::Ready);
    if (fault == 0) io.fast_supported = false;
    if (fault == 1) io.ignore_fast_clock = true;
    if (fault == 2) io.corrupt_fast_register = 6;
    if (fault == 3) io.suppress_completion = true;
    if (fault == 4) io.bad_status = true;
    if (fault == 5) io.bad_fifo = true;
    if (fault == 6) io.preempt_next_load = true;
    if (fault == 7) io.delay_overshoot = 10;
    const auto result = radio.transmitNative(command(), schedule(4, 5));
    assert(result.code != ResultCode::BenchSubmitted && result.code != ResultCode::Submitted);
    assert(result.frames_submitted <= 1 && !radio.ready() && !io.ce && !io.timed);
    assert(io.regs[0][0] == 0x0c && (io.regs[0x17][0] & 0x11) == 0x11);
    assert(io.begins == io.ends);
    const auto pulses = io.pulses.size();
    assert(radio.transmitNative(command(), schedule()).code == ResultCode::NotReady);
    assert(io.pulses.size() == pulses);  // No automatic retry/reinitialization.
    if (fault == 1 || fault == 6 || fault == 7)
      assert(result.code == ResultCode::TimingMissed && result.frames_submitted == 0);
    if (fault == 3)
      assert(result.code == ResultCode::Timeout);
  }
  for (unsigned stop_after : {0u, 3u, 9000u}) {
    TimedIo io;
    Radio radio(io);
    assert(radio.begin(bench()) == ResultCode::Ready);
    struct Context { TimedIo* io; unsigned count; } context{&io, stop_after};
    const auto cancel = [](void* raw) {
      auto* c = static_cast<Context*>(raw);
      return c->io->pulses.size() >= c->count;
    };
    const auto result = radio.transmitNative(command(), schedule(), cancel, &context);
    assert(result.code == ResultCode::Cancelled && result.frames_submitted == stop_after);
    assert(io.pulses.size() == stop_after && !io.ce && !io.timed && !radio.ready());
    assert(io.regs[0][0] == 0x0c && io.begins == io.ends);
  }
  // A transient cancellation during a CE-target wait remains latched. Calling
  // the callback again must not turn a revoked operation into a transmission.
  TimedIo io;
  Radio radio(io);
  assert(radio.begin(bench()) == ResultCode::Ready);
  unsigned calls = 0;
  const auto transient = [](void* context) { return ++*static_cast<unsigned*>(context) == 2; };
  const auto result = radio.transmitNative(command(), schedule(), transient, &calls);
  assert(result.code == ResultCode::Cancelled && io.pulses.empty() && calls == 2);
}
}  // namespace

int main() {
  complete_planner_vectors();
  body_and_phase_boundaries();
  preparation_experiments();
  invalid_plans();
  authorization_and_profiles();
  finite_timed_transmission();
  timing_faults_and_cancellation();
  std::cout << "native planner vectors, timed transport, scope and failure checks passed\n";
}
