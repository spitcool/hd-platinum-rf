/* SPDX-License-Identifier: GPL-2.0-or-later */
ENTRY(reset_handler)
MEMORY { RAM (rwx) : ORIGIN = 0x20000000, LENGTH = 256K }
PHDRS { image PT_LOAD FLAGS(5); storage PT_LOAD FLAGS(6); }
SECTIONS
{
    .vectors ORIGIN(RAM) : { KEEP(*(.vectors)) } > RAM :image
    .text : ALIGN(4) { *(.text*) *(.rodata*) } > RAM :image
    .data : ALIGN(4) { *(.data*) } > RAM :storage
    .bss (NOLOAD) : ALIGN(4) {
        __bss_start = .;
        *(.bss*) *(COMMON)
        . = ALIGN(4);
        __bss_end = .;
    } > RAM :storage
    __stack_top = ORIGIN(RAM) + LENGTH(RAM);
    __stack_bottom = __stack_top - 4096;
    ASSERT(__bss_end <= __stack_bottom, "capture data overlaps stack")
    ASSERT(SIZEOF(.vectors) == 256, "vector table must have 64 entries")
    /DISCARD/ : { *(.comment*) *(.note*) *(.ARM.exidx*) *(.ARM.extab*) }
}
