// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include "gateway_radio.h"

namespace platinum {
namespace radio {
namespace {
constexpr std::array<uint8_t, 3> kChannels = {33, 52, 71};
}

NativeAccess nativeAccess(const Policy& policy, Operation operation) {
  if (policy.route != Route::Native)
    return NativeAccess::Disabled;
  switch (operation) {
    case Operation::Position:
      return policy.native_position;
    case Operation::Jog:
      return policy.native_jog;
    case Operation::SecondaryPosition:
      return policy.native_secondary;
    default:
      return NativeAccess::Disabled;
  }
}

bool NativePlan::begin(const Command& command, const NativeSchedule& schedule) {
  count_ = ordinal_ = 0;
  const uint64_t count = uint64_t(schedule.command_frames) + schedule.followup_frames +
      schedule.preparation_frames;
  const bool preparation = schedule.preparation != NativePreparation::None;
  if (command.mask == 0 || (command.mask & (command.mask - 1)) != 0 ||
      (command.operation != Operation::Position && command.operation != Operation::Jog &&
       command.operation != Operation::SecondaryPosition) ||
      schedule.prior_alternate > 1 || schedule.command_frames == 0 ||
      schedule.followup_frames == 0 || schedule.slot_half_us != kNativeSlotHalfUs ||
      (preparation && command.operation != Operation::Position) ||
      (schedule.preparation != NativePreparation::None &&
       schedule.preparation != NativePreparation::Wake &&
       schedule.preparation != NativePreparation::CommandControl) ||
      preparation != (schedule.preparation_frames != 0) || schedule.preparation_frames % 3 != 0 ||
      count * kNativeSlotHalfUs > kNativeMaxDurationHalfUs)
    return false;
  bool channel_found = false;
  for (uint8_t index = 0; index < kChannels.size(); ++index) {
    if (schedule.prior_channel == kChannels[index]) {
      channel_index_ = index;
      channel_found = true;
    }
  }
  if (!channel_found)
    return false;
  command_ = command;
  schedule_ = schedule;
  count_ = static_cast<uint32_t>(count);
  alternate_ = 1 - schedule.prior_alternate;
  refresh_remaining_ = alternate_ ? 20 : 100;
  return true;
}

bool NativePlan::next(NativeEvent& event) {
  event = NativeEvent{};
  if (ordinal_ >= count_)
    return false;
  const bool preparing = ordinal_ < schedule_.preparation_frames;
  const bool wake = preparing && schedule_.preparation == NativePreparation::Wake;
  const bool followup = !preparing &&
      ordinal_ - schedule_.preparation_frames >= schedule_.command_frames;
  uint8_t mode = followup ? 0x32 :
      (command_.operation == Operation::SecondaryPosition ? 0x6d : 0x50);
  uint8_t value = command_.position;
  if (command_.operation == Operation::Jog) {
    value = 1;
    if (!followup) {
      // Original builder toggles on entry; scheduler decrements before CE.
      // Initial runs therefore contain 19/99 packets, then 20/100 packets.
      if (--refresh_remaining_ == 0) {
        alternate_ = 1 - alternate_;
        refresh_remaining_ = alternate_ ? 20 : 100;
      }
      mode = alternate_ ? 0x20 : 0x6a;
      value = alternate_ ? 0x6a : 1;
    }
  }
  // Primary and secondary position do not use Jog's refresh alternation.
  channel_index_ = (channel_index_ + 1) % kChannels.size();
  event.payload = {command_.room_id[0], command_.room_id[1], uint8_t(wake ? 0x01 : mode),
                   uint8_t(wake ? 0 : command_.mask), uint8_t(wake ? 0x80 : value)};
  event.ordinal = ordinal_;
  event.start_half_us = ordinal_ * kNativeSlotHalfUs;
  event.channel = kChannels[channel_index_];
  event.phase = preparing ? (wake ? NativePhase::Wake : NativePhase::CommandControl)
                         : followup ? NativePhase::Followup : NativePhase::Command;
  ++ordinal_;
  return true;
}
}  // namespace radio
}  // namespace platinum
