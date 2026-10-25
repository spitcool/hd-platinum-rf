// SPDX-FileCopyrightText: 2026 Christopher Spitler
// SPDX-License-Identifier: MIT
//! CoreS3 SE board wiring. Firmware talks to real SPI/I2C peripheral models;
//! no guest symbols, graphics calls, or driver functions are intercepted.
//! PMIC ADC inputs are fixed USB-powered fixtures; analog rails, audio and RTC
//! alarms are not simulated. GPIO and register behavior covers the fitted parts.
use std::sync::{Arc, Mutex};
use esp_soc::board::{BoardEdge, BoardModel, SpiPins, VirtualCycle};
use esp_soc::devices::DcsPanel;
use crate::i2c::I2cDevice;

const SDA: u8 = 12;
const SCL: u8 = 11;
const IRQ: u8 = 21;
const CS: u8 = 3;
const DC: u8 = 35;
const CPU_HZ: u64 = 240_000_000;

#[derive(Clone, Copy, Debug, PartialEq)]
enum Kind { Aw, Axp, Touch, Rtc }

struct State {
    aw: [u8; 256], axp: [u8; 256], ft: [u8; 256], rtc: [u8; 256],
    panel: DcsPanel,
    panel_command: u8, read_index: usize, external_index: u8,
    touch_down: bool, touch_x: u16, touch_y: u16,
    aw_pending: u8, irq_high: bool,
    cycle: u64, rtc_cycle: u64, version: u64, edges: Vec<BoardEdge>,
}

impl State {
    fn new() -> Self {
        let mut s = Self {
            aw: [0; 256], axp: [0; 256], ft: [0; 256], rtc: [0; 256],
            panel: DcsPanel::new(320, 240), panel_command: 0, read_index: 0,
            external_index: 0, touch_down: false, touch_x: 0, touch_y: 0,
            aw_pending: 0, irq_high: true, cycle: 0, rtc_cycle: 0, version: 0, edges: Vec::new(),
        };
        s.aw[0x10] = 0x23;
        s.aw[0x12] = 0xff;
        s.aw[0x13] = 0xff;
        s.axp[0x03] = 0x4a;
        s.axp[0x00] = 0x20; // USB VBUS good, no battery installed (SE).
        s.axp[0x36] = 0x07; s.axp[0x37] = 0xd0; // TS fixture 1 V.
        s.axp[0x38] = 0x13; s.axp[0x39] = 0x88; // VBUS fixture 5 V.
        s.axp[0x3a] = 0x0c; s.axp[0x3b] = 0xe4; // VSYS fixture 3.3 V.
        s.axp[0x80] = 0x01; // DCDC1 supplies the running board.
        s.ft[0xa3] = 0x64; s.ft[0xa6] = 0x01; s.ft[0xa8] = 0x11;
        s.rtc[5] = 1; s.rtc[6] = 4; s.rtc[7] = 1; s.rtc[8] = 0x26;
        s
    }
    fn touch_enabled(&self) -> bool { self.aw[2] & 1 != 0 && self.aw[4] & 1 == 0 && self.axp[0x10] & 1 == 0 }
    fn panel_enabled(&self) -> bool { self.aw[3] & 2 != 0 && self.aw[5] & 2 == 0 && self.axp[0x10] & 1 == 0 }
    fn visible(&self) -> bool {
        self.panel_enabled() && self.axp[0x90] & 0x80 != 0 && self.axp[0x99] != 0
            && self.panel.on && !self.panel.sleeping
    }
    fn input(&self, port: usize) -> u8 {
        let external = if port == 1 { if self.touch_down && self.touch_enabled() { 0xfb } else { 0xff } } else { 0xff };
        (self.aw[2 + port] & !self.aw[4 + port]) | (external & self.aw[4 + port])
    }
    fn irq(&mut self) {
        let high = self.aw_pending == 0;
        if high != self.irq_high {
            self.irq_high = high;
            self.edges.push(BoardEdge { cycle: self.cycle, pin: IRQ, level: high });
        }
    }
    fn touch(&mut self, x: u16, y: u16, down: bool) {
        let old = self.input(1);
        self.touch_down = down && self.touch_enabled();
        self.touch_x = x.min(319); self.touch_y = y.min(279);
        if (old ^ self.input(1)) & self.aw[5] & !self.aw[7] != 0 { self.aw_pending |= 2; }
        self.irq();
    }
    fn read(&mut self, kind: Kind, reg: u8) -> u8 {
        let i = reg as usize;
        match kind {
            Kind::Aw if reg < 2 => {
                let value = self.input(i);
                self.aw_pending &= !(1 << reg);
                self.irq();
                value
            }
            Kind::Aw => self.aw[i],
            Kind::Axp => self.axp[i],
            Kind::Rtc => self.rtc[i],
            Kind::Touch => match reg {
                0x02 => u8::from(self.touch_down && self.touch_enabled()),
                0x03 => ((self.touch_x >> 8) as u8 & 15) | 0x80,
                0x04 => self.touch_x as u8,
                0x05 => (self.touch_y >> 8) as u8 & 15,
                0x06 => self.touch_y as u8,
                0x07 => 32, 0x08 => 4,
                _ => self.ft[i],
            },
        }
    }
    fn write(&mut self, kind: Kind, reg: u8, value: u8) {
        let i = reg as usize;
        let panel_on = self.panel_enabled();
        let touch_on = self.touch_enabled();
        match kind {
            Kind::Aw if reg == 0x7f && value == 0 => {
                self.aw = [0; 256]; self.aw[0x10] = 0x23; self.aw[0x12] = 0xff; self.aw[0x13] = 0xff;
                self.aw_pending = 0;
            }
            Kind::Aw if reg > 1 && reg != 0x10 => self.aw[i] = value,
            Kind::Aw => {}
            Kind::Axp if (0x48..=0x4a).contains(&reg) => self.axp[i] &= !value,
            Kind::Axp if !matches!(reg, 0x00 | 0x01 | 0x03 | 0x34..=0x3d | 0xa4) => self.axp[i] = value,
            Kind::Axp => {}
            Kind::Touch if !matches!(reg, 0x02..=0x08 | 0xa3 | 0xa6 | 0xa8) => self.ft[i] = value,
            Kind::Touch => {}
            Kind::Rtc => self.rtc[i] = value,
        }
        if panel_on && !self.panel_enabled() {
            self.panel.reset(); self.panel.gram.fill(0); self.panel_command = 0;
        }
        if touch_on && !self.touch_enabled() {
            self.touch_down = false;
            self.ft[0xa4] = 0; self.ft[0xa5] = 0;
            self.aw_pending &= !2;
        }
        self.irq();
        self.version = self.version.wrapping_add(1);
    }
    fn advance(&mut self, cycle: u64) {
        self.cycle = cycle;
        if cycle < self.rtc_cycle { self.rtc_cycle = cycle; }
        let seconds = (cycle - self.rtc_cycle) / CPU_HZ;
        self.rtc_cycle += seconds * CPU_HZ;
        if self.rtc[0] & 0x20 != 0 { return; }
        for _ in 0..seconds.min(86400) {
            fn decimal(v: u8) -> u8 { (v >> 4) * 10 + (v & 15) }
            fn bcd(v: u8) -> u8 { ((v / 10) << 4) | v % 10 }
            let sec = decimal(self.rtc[2] & 0x7f) + 1;
            self.rtc[2] = bcd(sec % 60);
            if sec < 60 { continue; }
            let min = decimal(self.rtc[3] & 0x7f) + 1; self.rtc[3] = bcd(min % 60);
            if min < 60 { continue; }
            let hour = decimal(self.rtc[4] & 0x3f) + 1; self.rtc[4] = bcd(hour % 24);
            if hour < 24 { continue; }
            self.rtc[6] = (self.rtc[6] + 1) % 7;
            let month = decimal(self.rtc[7] & 0x1f).clamp(1, 12);
            let days = [31, if decimal(self.rtc[8]) % 4 == 0 {29} else {28},31,30,31,30,31,31,30,31,30,31][month as usize - 1];
            let day = decimal(self.rtc[5] & 0x3f) + 1;
            if day <= days { self.rtc[5] = bcd(day); continue; }
            self.rtc[5] = 1;
            self.rtc[7] = bcd(month % 12 + 1);
            if month == 12 { self.rtc[8] = bcd((decimal(self.rtc[8]) + 1) % 100); }
        }
    }
    fn spi(&mut self, dc: bool, tx: &[u8], rx_len: usize) -> Vec<u8> {
        if !self.panel_enabled() { return vec![0xff; rx_len]; }
        self.panel.dc = dc;
        for &byte in tx {
            if !dc { self.panel_command = byte; self.read_index = 0; }
            else if self.panel_command == 0xd9 { self.external_index = byte; }
            self.panel.byte(byte);
            self.version = self.version.wrapping_add(1);
        }
        let mut rx = Vec::with_capacity(rx_len);
        for _ in 0..rx_len {
            let value = match self.panel_command {
                // Bus_SPI returns the first wire byte in the low byte of W0.
                // This is the controller identity after its dummy clock.
                0x04 => [0xe3, 0x00, 0x00, 0x00].get(self.read_index).copied().unwrap_or(0),
                0xd3 => [0, 0, 0x93, 0x42].get(self.read_index).copied().unwrap_or(0),
                0xda => 0, 0xdb => 0x93, 0xdc => 0x42,
                0x0b => self.panel.madctl,
                0x0c => self.panel.colmod,
                // DD/CB are unsupported ILI9342E commands. Returning zero
                // keeps the firmware's genuine C/E identification on the C path.
                _ => 0,
            };
            rx.push(value); self.read_index += 1;
        }
        rx
    }
}

type Shared = Arc<Mutex<State>>;
struct Registers { state: Shared, kind: Kind, pointer: u8, first: bool }
impl Registers {
    fn new(state: &Shared, kind: Kind) -> Self { Self { state: state.clone(), kind, pointer: 0, first: true } }
}
impl I2cDevice for Registers {
    fn pins(&self) -> Option<(u8,u8)> { Some((SDA,SCL)) }
    fn start(&mut self, read: bool) -> bool {
        if !read { self.first = true; }
        self.kind != Kind::Touch || self.state.lock().unwrap().touch_enabled()
    }
    fn write(&mut self, byte: u8) -> bool {
        if self.first { self.pointer = byte; self.first = false; }
        else { self.state.lock().unwrap().write(self.kind, self.pointer, byte); self.pointer = self.pointer.wrapping_add(1); }
        true
    }
    fn read(&mut self) -> u8 {
        let byte = self.state.lock().unwrap().read(self.kind, self.pointer);
        self.pointer = self.pointer.wrapping_add(1);
        byte
    }
}

#[derive(Clone, Copy)]
enum Phase { Idle, Receive { byte: u8, bits: u8, address: bool }, Ack { ack: bool, ready: bool, read: bool }, Send { byte: u8, bits: u8 }, MasterAck(Option<bool>) }
struct SoftI2c {
    devices: Vec<(u8, Registers)>, selected: Option<usize>, phase: Phase,
    scl: bool, sda: bool, low: bool,
}
impl SoftI2c {
    fn new(state: &Shared) -> Self {
        Self { devices: [(0x58,Kind::Aw),(0x34,Kind::Axp),(0x38,Kind::Touch),(0x51,Kind::Rtc)].into_iter().map(|(a,k)|(a,Registers::new(state,k))).collect(), selected: None, phase: Phase::Idle, scl: true, sda: true, low: false }
    }
    fn send(&mut self) {
        let byte = self.selected.map(|i| self.devices[i].1.read()).unwrap_or(0xff);
        self.phase = Phase::Send { byte, bits: 0 }; self.low = byte & 0x80 == 0;
    }
    fn edge(&mut self, scl: bool, sda: bool) {
        if self.scl && scl && self.sda != sda && !self.low {
            self.low = false;
            if !sda { self.phase = Phase::Receive { byte: 0, bits: 0, address: true }; self.selected = None; }
            else { self.phase = Phase::Idle; }
        } else if !self.scl && scl {
            match self.phase {
                Phase::Receive { byte, bits, address } => {
                    let byte = (byte << 1) | u8::from(sda);
                    if bits == 7 {
                        let read = address && byte & 1 != 0;
                        let ack = if address {
                            self.selected = self.devices.iter().position(|(a,_)| *a == byte >> 1);
                            self.selected.is_some_and(|i| self.devices[i].1.start(read))
                        } else { self.selected.is_some_and(|i| self.devices[i].1.write(byte)) };
                        self.phase = Phase::Ack { ack, ready: false, read };
                    } else { self.phase = Phase::Receive { byte, bits: bits + 1, address }; }
                }
                Phase::Send { byte, bits } => {
                    self.phase = if bits == 7 { Phase::MasterAck(None) } else { Phase::Send { byte, bits: bits + 1 } };
                }
                Phase::MasterAck(None) => self.phase = Phase::MasterAck(Some(!sda)),
                _ => {}
            }
        } else if self.scl && !scl {
            match self.phase {
                Phase::Ack { ack, ready: false, read } => { self.low = ack; self.phase = Phase::Ack { ack, ready: true, read }; }
                Phase::Ack { ack, ready: true, read } => {
                    self.low = false;
                    if !ack { self.phase = Phase::Idle; }
                    else if read { self.send(); }
                    else { self.phase = Phase::Receive { byte: 0, bits: 0, address: false }; }
                }
                Phase::Send { byte, bits } => self.low = byte & (0x80 >> bits) == 0,
                Phase::MasterAck(None) => self.low = false,
                Phase::MasterAck(Some(ack)) => { if ack { self.send(); } else { self.low = false; self.phase = Phase::Idle; } }
                _ => {}
            }
        }
        self.scl = scl; self.sda = sda;
    }
}

pub struct CoreS3 {
    state: Shared, soft: SoftI2c, dc: bool, cs: bool,
    sda_driven: bool, release_sda: bool, gpio_events: u64,
}
impl CoreS3 {
    pub fn new() -> Self {
        let state = Arc::new(Mutex::new(State::new()));
        Self { soft: SoftI2c::new(&state), state, dc: false, cs: true, sda_driven: false, release_sda: false, gpio_events: 0 }
    }
}
impl Default for CoreS3 { fn default() -> Self { Self::new() } }
impl BoardModel for CoreS3 {
    fn name(&self) -> &'static str { "cores3-se" }
    fn gpio_output_at(&mut self, cycle: u64, changes: &[(u8,bool)], enabled: u64, output: u64) {
        self.state.lock().unwrap().advance(cycle);
        self.gpio_events += changes.len() as u64;
        self.dc = output & (1 << DC) != 0;
        self.cs = enabled & (1 << CS) == 0 || output & (1 << CS) != 0;
        let high = |pin: u8| enabled & (1 << pin) == 0 || output & (1 << pin) != 0;
        self.soft.edge(high(SCL), high(SDA));
    }
    fn uses_spi_pins(&self) -> bool { true }
    fn spi_transfer_pins(&mut self, host: u8, pins: SpiPins, tx: &[u8], rx_len: usize) -> Vec<u8> {
        if host != 2 || pins.sclk & (1 << 36) == 0 || pins.cs & (1 << CS) == 0
            || (!tx.is_empty() && pins.mosi & (1 << 37) == 0)
            || (rx_len != 0 && pins.miso != Some(37)) {
            return vec![0xff; rx_len];
        }
        self.state.lock().unwrap().spi(self.dc,tx,rx_len)
    }
    fn spi_transfer(&mut self, host: u8, tx: &[u8], rx_len: usize) -> Vec<u8> {
        if host == 2 && !self.cs { self.state.lock().unwrap().spi(self.dc,tx,rx_len) } else { vec![0xff;rx_len] }
    }
    fn i2c_devices(&mut self) -> Vec<(u8,u8,Box<dyn I2cDevice>)> {
        let mut result = Vec::new();
        for bus in 0..2 { for (address,kind) in [(0x58,Kind::Aw),(0x34,Kind::Axp),(0x38,Kind::Touch),(0x51,Kind::Rtc)] {
            result.push((bus,address,Box::new(Registers::new(&self.state,kind)) as Box<dyn I2cDevice>));
        }}
        result
    }
    fn touch(&mut self, x:u16,y:u16,down:bool) { self.state.lock().unwrap().touch(x,y,down); }
    fn touch_at(&mut self, cycle: VirtualCycle,x:u16,y:u16,down:bool) {
        let mut s=self.state.lock().unwrap(); s.advance(cycle); s.touch(x,y,down);
    }
    fn input_levels(&self) -> Vec<(u8,bool)> { vec![(IRQ,self.state.lock().unwrap().irq_high)] }
    fn advance_to(&mut self, cycle: VirtualCycle) { self.state.lock().unwrap().advance(cycle); }
    fn take_edges(&mut self) -> Vec<BoardEdge> {
        let mut s=self.state.lock().unwrap();
        if self.soft.low != self.sda_driven {
            self.sda_driven = self.soft.low;
            if self.soft.low { let cycle=s.cycle; s.edges.push(BoardEdge {cycle,pin:SDA,level:false}); }
            else { self.release_sda=true; }
        }
        std::mem::take(&mut s.edges)
    }
    fn released_inputs(&mut self) -> Vec<u8> {
        if self.release_sda { self.release_sda=false; vec![SDA] } else { Vec::new() }
    }
    fn display(&self) -> Option<(u32,u32,Vec<u16>,u64)> {
        let s=self.state.lock().unwrap();
        let pixels=if s.visible() { s.panel.gram.iter().map(|&p| if s.panel.inverted {p} else {!p}).collect() } else {vec![0;320*240]};
        Some((320,240,pixels,s.version))
    }
    fn display_version(&self)->u64 { self.state.lock().unwrap().version }
    fn display_frames(&self)->u64 { self.state.lock().unwrap().panel.frames }
    fn display_quiet_push(&self)->bool { true }
    fn gpio_events(&self)->u64 {self.gpio_events}
    fn report(&self)->String {
        let s=self.state.lock().unwrap();
        format!("[emu] cores3-se: {} pixels, {} RAMWR, MADCTL={:02x}, visible={}, AW={:02x}/{:02x}, IRQ={}, touch={}",s.panel.pixels_written,s.panel.frames,s.panel.madctl,s.visible(),s.aw[2],s.aw[3],s.irq_high,s.touch_down)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    fn write(dev: &mut Registers, reg:u8, bytes:&[u8]) {assert!(dev.start(false));dev.write(reg);for &b in bytes{dev.write(b);}dev.stop();}
    fn read(dev: &mut Registers, reg:u8,n:usize)->Vec<u8>{assert!(dev.start(false));dev.write(reg);assert!(dev.start(true));(0..n).map(|_|dev.read()).collect()}
    fn power(s:&Shared){let mut s=s.lock().unwrap();s.write(Kind::Aw,2,5);s.write(Kind::Aw,3,3);s.write(Kind::Aw,4,0x18);s.write(Kind::Aw,5,0x0c);s.write(Kind::Axp,0x90,0xbf);s.write(Kind::Axp,0x99,24);}
    #[test] fn registers_and_bus_power_readback(){let b=CoreS3::new();let mut aw=Registers::new(&b.state,Kind::Aw);let mut axp=Registers::new(&b.state,Kind::Axp);assert_eq!(read(&mut aw,0x10,1),[0x23]);assert_eq!(read(&mut axp,3,1),[0x4a]);write(&mut aw,2,&[7,0x83]);assert_eq!(read(&mut aw,2,2),[7,0x83]);write(&mut aw,0x10,&[0]);assert_eq!(read(&mut aw,0x10,1),[0x23]);write(&mut axp,0x90,&[0xbf]);assert_eq!(read(&mut axp,0x90,1),[0xbf]);}
    #[test] fn touch_press_release_and_reset(){let mut b=CoreS3::new();power(&b.state);let mut ft=Registers::new(&b.state,Kind::Touch);let mut aw=Registers::new(&b.state,Kind::Aw);assert_ne!(read(&mut ft,0xa3,6)[5],0);b.touch(120,80,true);assert_eq!(b.input_levels(),[(IRQ,false)]);assert_eq!(read(&mut ft,2,5),[1,0x80,120,0,80]);b.touch(120,80,false);assert_eq!(read(&mut ft,2,1),[0]);read(&mut aw,0,1);assert_eq!(b.input_levels(),[(IRQ,false)]);read(&mut aw,1,1);assert_eq!(b.input_levels(),[(IRQ,true)]);b.touch(20,30,true);write(&mut aw,2,&[4]);assert!(!ft.start(true));assert!(!b.state.lock().unwrap().touch_down);}
    #[test] fn spi_pixels_and_power_gating(){let b=CoreS3::new();power(&b.state);let mut s=b.state.lock().unwrap();assert_eq!(s.spi(false,&[4],0),[]);assert_eq!(s.spi(true,&[],4),[0xe3,0,0,0]);for c in [0x11,0x29,0x21]{s.spi(false,&[c],0);}s.spi(false,&[0x2a],0);s.spi(true,&[0,0,0,1],0);s.spi(false,&[0x2b],0);s.spi(true,&[0,0,0,0],0);s.spi(false,&[0x2c],0);s.spi(true,&[0xf8,0],0);s.spi(true,&[7,0xe0],0);assert_eq!(&s.panel.gram[..2],&[0xf800,0x07e0]);drop(s);assert_eq!(&b.display().unwrap().2[..2],&[0xf800,0x07e0]);b.state.lock().unwrap().write(Kind::Axp,0x90,0x3f);assert!(b.display().unwrap().2.iter().all(|&p|p==0));b.state.lock().unwrap().write(Kind::Aw,3,1);assert!(b.state.lock().unwrap().panel.gram.iter().all(|&p|p==0));}
    #[test] fn soft_i2c_probe_and_repeated_start(){let s=Arc::new(Mutex::new(State::new()));let mut bus=SoftI2c::new(&s);fn start(b:&mut SoftI2c){b.edge(false,true);b.edge(true,true);b.edge(true,false);b.edge(false,false);}fn byte(b:&mut SoftI2c,v:u8){for bit in (0..8).rev(){b.edge(false,v&(1<<bit)!=0);b.edge(true,v&(1<<bit)!=0);b.edge(false,v&(1<<bit)!=0);}assert!(b.low);b.edge(true,true);b.edge(false,true);}start(&mut bus);byte(&mut bus,0xb0);byte(&mut bus,0x10);start(&mut bus);byte(&mut bus,0xb1);let mut value=0u8;for _ in 0..8{value=(value<<1)|u8::from(!bus.low);bus.edge(true,true);bus.edge(false,true);}assert_eq!(value,0x23);bus.edge(true,true);bus.edge(false,true);assert!(!bus.low);}
}
