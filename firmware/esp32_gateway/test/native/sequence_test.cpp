// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: GPL-2.0-or-later
#include <cassert>
#include <cstdint>
#include <iostream>
#include <optional>

#include "sequence_store.h"

using namespace platinum::radio;

struct MemoryStore {
  std::optional<uint32_t> next;
  bool fail_read = false, corrupt = false, fail_write = false;
  bool commit_on_failure = false, discard_write = false, fail_verification = false;
  unsigned writes = 0;
  SequenceHooks hooks() {
    return {[this](uint32_t& value) {
              if (fail_read)
                return SequenceRead::Failure;
              if (corrupt)
                return SequenceRead::Corrupt;
              if (!next)
                return SequenceRead::Absent;
              value = *next;
              return SequenceRead::Present;
            },
            [this](uint32_t value) {
              ++writes;
              if ((!fail_write || commit_on_failure) && !discard_write)
                next = value;
              if (fail_verification)
                fail_read = true;
              return !fail_write;
            }};
  }
};

void reserve_and_restart() {
  MemoryStore memory;
  SequenceStore store(memory.hooks());
  assert(!store.allocate() && store.status() == SequenceStatus::Absent);
  assert(store.initialize(255) && memory.next == 255);
  assert(!store.initialize(0) && memory.next == 255);
  assert(store.allocate() == 255 && memory.next == 256);
  // The caller could lose power here before transmission. New store must consume
  // 256 next, never assume unobserved RF means the old reservation is reusable.
  SequenceStore reboot(memory.hooks());
  assert(reboot.allocate() == 256 && memory.next == 257);
  assert(reboot.allocate() == 257 && memory.next == 258);
  memory.next = 256;
  assert(!reboot.allocate() && reboot.status() == SequenceStatus::Corrupt);
  memory.next = 1000;
  assert(!reboot.allocate());  // Detected rollback latches until explicit recovery.
}

void interrupted_commit() {
  for (bool committed : {false, true}) {
    MemoryStore memory;
    memory.next = 100;
    memory.fail_write = true;
    memory.commit_on_failure = committed;
    SequenceStore store(memory.hooks());
    assert(!store.allocate() && store.status() == SequenceStatus::StorageFault);
    assert(memory.next == (committed ? 101u : 100u));
    memory.fail_write = false;
    assert(!store.allocate() && memory.writes == 1);
    assert(!store.initialize(0));
    SequenceStore reboot(memory.hooks());
    assert(reboot.allocate() == (committed ? 101u : 100u));
    // Reuse after an uncommitted write is safe: allocate never returned it and
    // hence no caller was permitted to transmit it.
  }
  MemoryStore memory;
  memory.next = 123;
  memory.fail_verification = true;
  SequenceStore store(memory.hooks());
  assert(!store.allocate() && memory.next == 124);
  memory.fail_read = false;
  memory.fail_verification = false;
  assert(!store.allocate() && store.status() == SequenceStatus::StorageFault);
  SequenceStore reboot(memory.hooks());
  assert(reboot.allocate() == 124);
}

void corrupted_and_exhausted() {
  MemoryStore memory;
  memory.next = 65535;
  SequenceStore store(memory.hooks());
  assert(store.allocate() == 65535 && memory.next == 65536);
  assert(!store.allocate() && store.status() == SequenceStatus::Exhausted);
  memory.next = 0;
  assert(!store.allocate() && memory.writes == 1);
  memory.next = 65537;
  SequenceStore invalid(memory.hooks());
  assert(!invalid.allocate() && invalid.status() == SequenceStatus::Corrupt);
  memory.next = 10;
  memory.discard_write = true;
  SequenceStore stale(memory.hooks());
  assert(!stale.allocate() && stale.status() == SequenceStatus::StorageFault);
  memory.discard_write = false;
  SequenceStore missing(memory.hooks());
  assert(missing.allocate() == 10);
  memory.next.reset();
  assert(!missing.allocate() && missing.status() == SequenceStatus::Corrupt);
  memory.corrupt = true;
  SequenceStore bad_crc(memory.hooks());
  assert(!bad_crc.allocate() && bad_crc.status() == SequenceStatus::Corrupt);
  memory.corrupt = false;
  memory.fail_read = true;
  SequenceStore unreadable(memory.hooks());
  assert(!unreadable.initialize(0) && unreadable.status() == SequenceStatus::StorageFault);
}

int main() {
  reserve_and_restart();
  interrupted_commit();
  corrupted_and_exhausted();
  std::cout << "durable ordinal reservation and failure checks passed\n";
}
