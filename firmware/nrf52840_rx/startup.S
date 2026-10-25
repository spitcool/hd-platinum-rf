/* SPDX-License-Identifier: GPL-2.0-or-later */
.syntax unified
.cpu cortex-m4
.thumb

.section .vectors,"a",%progbits
.balign 256
.global __vectors
__vectors:
    .word __stack_top
    .word reset_handler
    .rept 14
    .word unexpected_irq_handler
    .endr
    .word unexpected_irq_handler /* external IRQ0 */
    .word radio_irq_handler      /* IRQ1 */
    .rept 25
    .word unexpected_irq_handler
    .endr
    .word timer_irq_handler      /* IRQ27 = TIMER4 */
    .rept 20
    .word unexpected_irq_handler
    .endr

.section .text.reset_handler,"ax",%progbits
.thumb_func
.global reset_handler
.type reset_handler,%function
reset_handler:
    cpsid i
    /* Disable event routes and RADIO before any RAM initialization. */
    ldr r0, =0x4001f508
    movs r1, #0
    mvns r1, r1
    str r1, [r0]
    ldr r0, =0x40001ffc
    movs r1, #0
    str r1, [r0]
    dsb
    ldr r0, =__stack_top
    msr msp, r0
    movs r0, #0
    msr control, r0
    isb
    ldr r0, =0xe000ed08
    ldr r1, =__vectors
    str r1, [r0]
    dsb
    isb
    ldr r0, =__bss_start
    ldr r1, =__bss_end
    movs r2, #0
1:  cmp r0, r1
    bhs 2f
    str r2, [r0], #4
    b 1b
2:  bl firmware_main
3:  b 3b
.size reset_handler, .-reset_handler
