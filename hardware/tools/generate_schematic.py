#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Christopher Spitler
# SPDX-License-Identifier: AGPL-3.0-or-later
"""Generate the editable, self-contained KiCad 9 carrier schematic.

The electrical pin/net source of truth is design/board-spec.json. Symbols here
are original simple drawings, with actual electrical pin types. No external
symbol library is needed to open or edit the generated schematic.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
import uuid

ROOT = Path(__file__).resolve().parents[1]
SPEC = json.loads((ROOT / "design/board-spec.json").read_text())
NAME = SPEC["name"]
ROOT_UUID = str(uuid.uuid5(uuid.NAMESPACE_URL, "hd-platinum/root"))


def uid(key: str) -> str:
    return str(uuid.uuid5(uuid.NAMESPACE_URL, "hd-platinum/" + key))


def q(value: object) -> str:
    return json.dumps(str(value), ensure_ascii=False)


def f(value: float) -> str:
    return f"{value:.4f}".rstrip("0").rstrip(".") or "0"


def effects(size: float = 1.27, hidden: bool = False, justify: str = "") -> str:
    return f"(effects (font (size {f(size)} {f(size)}))" + (f" (justify {justify})" if justify else "") + (" (hide yes)" if hidden else "") + ")"


def prop(name: str, value: object, x: float, y: float, hidden: bool = False, size: float = 1.27) -> str:
    return f"(property {q(name)} {q(value)} (at {f(x)} {f(y)} 0) {effects(size, hidden)})"


def pin(number: str, name: str, x: float, y: float, direction: int, electrical: str = "passive", length: float = 5.08) -> dict:
    return {"n": number, "name": name, "x": x, "y": y, "a": direction, "type": electrical, "length": length}


def pin_expr(p: dict) -> str:
    return (f"(pin {p['type']} line (at {f(p['x'])} {f(p['y'])} {p['a']}) (length {f(p['length'])}) "
            f"(name {q(p['name'])} {effects(1.016)}) (number {q(p['n'])} {effects(1.016)}))")


def line(x1: float, y1: float, x2: float, y2: float) -> str:
    return f"(polyline (pts (xy {f(x1)} {f(y1)}) (xy {f(x2)} {f(y2)})) (stroke (width 0.254) (type default)) (fill (type none)))"


def rectangle(x1: float, y1: float, x2: float, y2: float) -> str:
    return f"(rectangle (start {f(x1)} {f(y1)}) (end {f(x2)} {f(y2)})(stroke (width 0.254) (type default)) (fill (type background)))"


PINS: dict[str, list[dict]] = {}
SYMBOLS: list[str] = []


def library_symbol(name: str, reference: str, pins: list[dict], graphics: str, *, power: bool = False, pin_names: bool = True) -> None:
    PINS[name] = pins
    SYMBOLS.append(
        f'(symbol "HDPlatinum:{name}" ' + ("(power) " if power else "") +
        f'(pin_names (offset 1.016){"" if pin_names else " (hide yes)"}) (in_bom {"no" if power else "yes"}) (on_board {"no" if power else "yes"}) '
        + prop("Reference", reference, 0, 5.08, power)
        + prop("Value", name, 0, -5.08, power)
        + f'(symbol "{name}_0_1" {graphics})'
        + f'(symbol "{name}_1_1" ' + " ".join(pin_expr(p) for p in pins) + "))"
    )


bus_labels = {
    1: "GND", 2: "G10 / RF_IRQ", 3: "GND", 4: "G8 / RF_MISO",
    5: "GND", 6: "RESET", 7: "G37 / ETH_MOSI", 8: "G5 / RF_MOSI",
    9: "G35 / ETH_MISO", 10: "G9 / ETH_CS", 11: "G36 / ETH_SCK", 12: "HOST_3V3",
    13: "G44 / UART0_RX", 14: "G43 / UART0_TX", 15: "G18 / RF_CSN", 16: "G17 / RF_CE",
    17: "G12 / SYS_SDA", 18: "G11 / SYS_SCL", 19: "G2 / PA_SDA", 20: "G1 / PA_SCL",
    21: "G6 / RF_SCK", 22: "G7 / ETH_RESET", 23: "G13 / MIC", 24: "G0 / BOOT",
    25: "HPWR / HOST_NC", 26: "G14 / ETH_IRQ", 27: "HPWR / HOST_NC", 28: "BUS_5V",
    29: "HPWR / HOST_NC", 30: "BAT",
}
bus_pins = [pin(str(n), bus_labels[n], -25.4 if n % 2 else 25.4,
                35.56 - ((n - 1) // 2) * 5.08, 0 if n % 2 else 180)
            for n in range(1, 31)]
library_symbol("M5Bus_A089", "J", bus_pins, rectangle(-20.32, 38.1, 20.32, -38.1))
radio_pins = [
    pin("1", "VCC", 0, 43.18, 270, "power_in", 10.16),
    pin("2", "GND", -7.62, -43.18, 90, "power_in", 10.16),
    pin("3", "CE", -25.4, 25.4, 0, "input"),
    pin("4", "CSN", -25.4, 15.24, 0, "input"),
    pin("5", "SCK", -25.4, 5.08, 0, "input"),
    pin("6", "MOSI", -25.4, -5.08, 0, "input"),
    pin("7", "MISO", -25.4, -15.24, 0, "tri_state"),
    pin("8", "IRQ", -25.4, -25.4, 0, "output"),
    pin("9", "GND", 0, -43.18, 90, "power_in", 10.16),
    pin("10", "GND", 7.62, -43.18, 90, "power_in", 10.16),
    pin("11", "ANT / 50R", 25.4, 25.4, 180, "passive"),
]
library_symbol("RF2401F20", "U", radio_pins, rectangle(-20.32, 33.02, 20.32, -33.02))
ldo_pins = [pin("1", "IN", -10.16, 7.62, 0, "power_in"),
            pin("2", "GND", 0, -12.7, 90, "power_in"),
            pin("3", "EN", -10.16, -7.62, 0, "input"),
            pin("4", "NC", 10.16, -7.62, 180, "no_connect"),
            pin("5", "OUT", 10.16, 7.62, 180, "power_out")]
library_symbol("TLV75533PDBVR", "U", ldo_pins, rectangle(-5.08, 10.16, 5.08, -10.16))
passive_h = [pin("1", "~", -7.62, 0, 0, length=5.08), pin("2", "~", 7.62, 0, 180, length=5.08)]
passive_v = [pin("1", "~", 0, 7.62, 270, length=5.08), pin("2", "~", 0, -7.62, 90, length=5.08)]
library_symbol("R_H", "R", passive_h, rectangle(-2.54, 1.016, 2.54, -1.016), pin_names=False)
library_symbol("R_V", "R", passive_v, rectangle(-1.016, 2.54, 1.016, -2.54), pin_names=False)
library_symbol("Ferrite", "FB", passive_h, rectangle(-2.54, 1.524, 2.54, -1.524) + line(-1.27, -2.032, 1.27, 2.032), pin_names=False)
cap_pins = [pin("1", "~", 0, 7.62, 270, length=6.604), pin("2", "~", 0, -7.62, 90, length=6.604)]
library_symbol("C", "C", cap_pins, line(-2.54, 1.016, 2.54, 1.016) + line(-2.54, -1.016, 2.54, -1.016), pin_names=False)
coax_pins = [pin("1", "ANT", -7.62, 0, 0), pin("2", "GND", 0, -7.62, 90)]
library_symbol("UFL", "J", coax_pins,
               '(circle (center 0 0) (radius 2.54) (stroke (width 0.254) (type default)) (fill (type none)))'
               + '(circle (center 0 0) (radius 0.762) (stroke (width 0.254) (type default)) (fill (type none)))'
               + line(-2.54, 0, -0.762, 0) + line(0, -2.54, 0, -0.762), pin_names=False)
library_symbol("TestPoint", "TP", [pin("1", "~", 0, -2.54, 90, length=2.54)],
               '(circle (center 0 0.762) (radius 0.762) (stroke (width 0.254) (type default)) (fill (type none)))', pin_names=False)
library_symbol("PWR_FLAG", "#FLG", [pin("1", "pwr", 0, 0, 90, "power_out", 0)],
               line(0, 0, 0, 1.27) + line(0, 1.27, -1.27, 1.905) + line(-1.27, 1.905, 0, 2.54)
               + line(0, 2.54, 1.27, 1.905) + line(1.27, 1.905, 0, 1.27), power=True, pin_names=False)

PLACEMENTS = {
    "J1": ("M5Bus_A089", 66.04, 99.06, 0),
    "FB1": ("Ferrite", 152.4, 66.04, 0),
    "U2": ("TLV75533PDBVR", 251.46, 73.66, 0),
    "C1": ("C", 177.8, 83.82, 0), "C2": ("C", 203.2, 83.82, 0),
    "C3": ("C", 284.48, 83.82, 0),
    "R9": ("R_V", 228.6, 101.6, 0),
    "U1": ("RF2401F20", 309.88, 190.5, 0),
    "J2": ("UFL", 370.84, 165.1, 0),
    "C4": ("C", 353.06, 132.08, 0), "C5": ("C", 383.54, 132.08, 0),
    "R1": ("R_H", 238.76, 165.1, 0), "R2": ("R_H", 238.76, 175.26, 0),
    "R3": ("R_H", 238.76, 185.42, 0), "R4": ("R_H", 238.76, 195.58, 0),
    "R5": ("R_H", 238.76, 205.74, 180),
    "R6": ("R_V", 142.24, 213.36, 0), "R7": ("R_V", 175.26, 213.36, 180),
    "R8": ("R_V", 195.58, 213.36, 0),
    "TP1": ("TestPoint", 25.4, 254, 0), "TP2": ("TestPoint", 55.88, 254, 0),
    "TP3": ("TestPoint", 86.36, 254, 0), "TP4": ("TestPoint", 116.84, 254, 0),
    "TP5": ("TestPoint", 147.32, 254, 0), "TP6": ("TestPoint", 177.8, 254, 0),
    "TP7": ("TestPoint", 208.28, 254, 0),
}

OBJECTS: list[str] = []
COORDS: dict[tuple[str, str], tuple[float, float]] = {}
NET_PINS: dict[str, list[tuple[str, str]]] = {}
WIRES: list[tuple[tuple[float, float], tuple[float, float]]] = []
ANCHORS: set[tuple[float, float]] = set()


def actual_pin(ref: str, p: dict) -> tuple[float, float]:
    _, x, y, angle = PLACEMENTS[ref]
    a = math.radians(angle)
    return round(x + p["x"] * math.cos(a) - p["y"] * math.sin(a), 4), round(y - p["x"] * math.sin(a) - p["y"] * math.cos(a), 4)


def component(comp: dict) -> None:
    ref = comp["ref"]
    kind, x, y, a = PLACEMENTS[ref]
    props = [prop("Reference", ref, x, y - (35.56 if ref == "U1" else 43.18 if ref == "J1" else 5.08)),
             prop("Value", comp["value"], x, y - (38.1 if ref == "U1" else 46.99 if ref == "J1" else 8.89), size=1.016),
             prop("Footprint", comp["footprint"], x, y, True),
             prop("Datasheet", "", x, y, True),
             prop("MPN", comp["mpn"], x, y, True),
             prop("Manufacturer", comp["manufacturer"], x, y, True)]
    if ref.startswith("C") or (ref.startswith("R") and kind == "R_V"):
        props[0] = prop("Reference", ref, x + 5.08, y - 2.54)
        props[1] = prop("Value", comp["value"], x + 8.89, y + 1.27, size=1.016)
    if ref == "U2":
        props[0] = prop("Reference", ref, x, y - 14.605)
        props[1] = prop("Value", comp["value"], x, y - 18.415, size=1.016)
    if ref == "U1":
        props[0] = prop("Reference", ref, x - 12.7, y - 35.56)
        props[1] = prop("Value", comp["value"], x - 12.7, y - 38.1, size=1.016)
    if kind == "R_H":
        props[0] = prop("Reference", ref, x - 3.81, y - 2.54)
        props[1] = prop("Value", comp["value"], x + 3.81, y - 2.54, size=1.016)
    if kind == "TestPoint":
        props[0] = prop("Reference", ref, x, y - 3.81)
        props[1] = prop("Value", comp["value"], x, y - 6.35, size=1.016)
    for p in PINS[kind]:
        COORDS[ref, p["n"]] = actual_pin(ref, p)
        net = comp["pins"].get(p["n"])
        if net:
            NET_PINS.setdefault(net, []).append((ref, p["n"]))
    pins = " ".join(f'(pin {q(p["n"])} (uuid {uid(ref + "/pin/" + p["n"])}))' for p in PINS[kind])
    instances = f'(instances (project {q(NAME)} (path "/{ROOT_UUID}" (reference {q(ref)}) (unit 1))))'
    in_bom = "no" if ref.startswith("TP") else "yes"
    OBJECTS.append(f'(symbol (lib_id "HDPlatinum:{kind}") (at {f(x)} {f(y)} {a}) (unit 1) (in_bom {in_bom}) (on_board yes) (dnp no) (uuid {uid(ref)}) {" ".join(props)} {pins} {instances})')


for item in SPEC["components"]:
    component(item)


def wire(a: tuple[float, float], b: tuple[float, float]) -> None:
    if a == b:
        return
    WIRES.append((tuple(round(v, 4) for v in a), tuple(round(v, 4) for v in b)))


def label(net: str, x: float, y: float, angle: int = 0) -> None:
    point = (round(x, 4), round(y, 4))
    ANCHORS.add(point)
    horizontal = [(a, b) for a, b in WIRES if a[1] == b[1] == point[1]
                  and min(a[0], b[0]) <= point[0] <= max(a[0], b[0])]
    # Keep label boxes off the wire. An interior label gets a short branch;
    # an endpoint label faces outwards from the connected wire.
    if any(min(a[0], b[0]) < point[0] < max(a[0], b[0]) for a, b in horizontal):
        y -= 2.54
        wire(point, (x, y))
        ANCHORS.add((round(x, 4), round(y, 4)))
    elif any(point[0] == min(a[0], b[0]) for a, b in horizontal):
        angle = 180
    justify = "right" if angle == 180 else "left"
    OBJECTS.append(f'(global_label {q(net)} (shape passive) (at {f(x)} {f(y)} {angle}) {effects(1.016, justify=justify)} (uuid {uid("label/" + repr((net, x, y, angle)))}))')


def junction(x: float, y: float) -> None:
    ANCHORS.add((round(x, 4), round(y, 4)))
    OBJECTS.append(f'(junction (at {f(x)} {f(y)}) (diameter 0) (color 0 0 0 0) (uuid {uid("junction/" + repr((x, y)))}))')


def nc(x: float, y: float) -> None:
    OBJECTS.append(f'(no_connect (at {f(x)} {f(y)}) (uuid {uid("nc/" + repr((x, y)))}))')


def text(value: str, x: float, y: float, size: float = 1.27) -> None:
    OBJECTS.append(f'(text {q(value)} (at {f(x)} {f(y)} 0) {effects(size, justify="left top")} (uuid {uid("text/" + value)}))')


def flag(net: str, x: float, y: float, index: int) -> None:
    ref = f"#FLG0{index}"
    OBJECTS.append(f'(symbol (lib_id "HDPlatinum:PWR_FLAG") (at {f(x)} {f(y)} 0) (unit 1) (in_bom no) (on_board no) (dnp no) (uuid {uid(ref)}) '
                   + prop("Reference", ref, x, y - 3.81, True) + prop("Value", "PWR_FLAG", x, y, True)
                   + f'(pin "1" (uuid {uid(ref + "/pin/1")}))'
                   + f'(instances (project {q(NAME)} (path "/{ROOT_UUID}" (reference {q(ref)}) (unit 1)))))')
    label(net, x, y)


# Every contact appears on the schematic. NC means the carrier does not tap
# that contact, not that the stack-through connector loses the connection.
bus = SPEC["components"][0]
for p in PINS["M5Bus_A089"]:
    x, y = COORDS["J1", p["n"]]
    net = bus["pins"].get(p["n"])
    if not net:
        nc(x, y)
    elif int(p["n"]) % 2:
        wire((x - 12.7, y), (x, y)); label(net, x - 12.7, y)
    else:
        wire((x, y), (x + 12.7, y)); label(net, x + 12.7, y)

# Continuous power drawing.
wire((127, 66.04), COORDS["FB1", "1"]); label("BUS_5V", 127, 66.04)
wire(COORDS["FB1", "2"], COORDS["U2", "1"]); label("LDO_IN", 215.9, 66.04)
for ref in ("C1", "C2"):
    x, y = COORDS[ref, "1"]
    wire((x, 66.04), (x, y)); junction(x, 66.04)
wire(COORDS["U2", "5"], (284.48, 66.04)); label("RF_3V3", 284.48, 66.04)
x, y = COORDS["C3", "1"]
wire((x, 66.04), (x, y)); junction(x, 66.04)
for ref in ("C1", "C2", "C3", "U2"):
    x, y = COORDS[ref, "2"]
    wire((x, y), (x, y + 5.08)); label("GND", x, y + 5.08)
x, y = COORDS["U2", "3"]
wire((x - 12.7, y), (x, y)); label("HOST_3V3", x - 12.7, y)
nc(*COORDS["U2", "4"])
for n, net in SPEC["components"][[c["ref"] for c in SPEC["components"]].index("R9")]["pins"].items():
    x, y = COORDS["R9", n]; end_y = y - 3.81 if n == "1" else y + 3.81
    wire((x, y), (x, end_y)); label(net, x, end_y)
# These flags explicitly model power supplied by the host/base and continuity
# across FB1. RF_3V3 is driven by U2's actual power-output pin.
for i, (net, x) in enumerate((("BUS_5V", 142.24), ("LDO_IN", 167.64), ("HOST_3V3", 193.04), ("GND", 269.24)), 1):
    flag(net, x, 109.22, i)

# Radio connections and source-series damping.
for i, radio_pin in enumerate(("3", "4", "5", "6", "7"), 1):
    ref = f"R{i}"
    component_spec = next(c for c in SPEC["components"] if c["ref"] == ref)
    # R5 pin 1 is on the radio side because MISO flows from the radio.
    host_pin = "2" if ref == "R5" else "1"
    rf_pin = "1" if ref == "R5" else "2"
    x, y = COORDS[ref, host_pin]
    wire((x - 20.32, y), (x, y)); label(component_spec["pins"][host_pin], x - 20.32, y)
    wire(COORDS[ref, rf_pin], COORDS["U1", radio_pin])
    rx, ry = COORDS[ref, rf_pin]
    label(component_spec["pins"][rf_pin], rx + 5.08, ry)
x, y = COORDS["U1", "8"]
wire((x - 33.02, y), (x, y)); label("RF_IRQ", x - 33.02, y)
x, y = COORDS["U1", "1"]
wire((x, y - 7.62), (x, y)); label("RF_3V3", x, y - 7.62)
for p in ("2", "9", "10"):
    x, y = COORDS["U1", p]; wire((x, y), (x, 238.76))
wire((302.26, 238.76), (317.5, 238.76)); junction(309.88, 238.76); label("GND", 309.88, 238.76)
wire(COORDS["U1", "11"], COORDS["J2", "1"]); label("ANT", 342.9, 165.1)
x, y = COORDS["J2", "2"]
wire((x, y), (x, y + 5.08)); label("GND", x, y + 5.08)
for ref in ("C4", "C5"):
    for p, net in (("1", "RF_3V3"), ("2", "GND")):
        x, y = COORDS[ref, p]; dy = -5.08 if p == "1" else 5.08
        wire((x, y), (x, y + dy)); label(net, x, y + dy)

# Radio-side default logic levels. R7 is drawn upwards to its positive rail.
for ref in ("R6", "R7", "R8"):
    c = next(c for c in SPEC["components"] if c["ref"] == ref)
    for p, net in c["pins"].items():
        x, y = COORDS[ref, p]
        dy = -5.08 if y < PLACEMENTS[ref][2] else 5.08
        wire((x, y), (x, y + dy)); label(net, x, y + dy)

for c in SPEC["components"]:
    if c["ref"].startswith("TP"):
        x, y = COORDS[c["ref"], "1"]
        wire((x, y), (x, y + 5.08)); label(c["pins"]["1"], x, y + 5.08)

text("HD PLATINUM 2.4 GHz RADIO CARRIER", 15.24, 15.24, 2.54)
text("REV A  |  ENGINEERING FIRST ARTICLE - NOT PRODUCTION RELEASED", 15.24, 21.59, 1.524)
text("CoreS3-SE K128-SE + M032 frame + Base LAN v1.2 K012-B-V12", 15.24, 27.94)
text("HOST / STACK-THROUGH BUS", 15.24, 39.37, 1.524)
text("DEDICATED 3.3 V RADIO SUPPLY", 127, 39.37, 1.524)
text("C1/C2 at U2 IN; C3 at U2 OUT.\nU2 EN follows host rail; RF_3V3 is NOT tied to HOST_3V3.\nAll MLCC values are nominal: account for DC-bias derating.", 307.34, 55.88, 1.016)
text("Power flags identify external supply rails / continuity through FB1.", 127, 115.57, 1.016)
text("DEDICATED RADIO SPI / DEFAULT STATES", 127, 134.62, 1.524)
text("C4/C5 at U1 VCC/GND", 340.36, 111.76, 1.016)
text("50 ohm controlled trace.\nNo RF test-pad stubs.\nU.FL to external antenna.\nANT is pin 11, never pin 9.", 342.9, 182.88, 1.016)
text("NiceRF current V3.1 numbering\nRF_PWR <= 2; default RF_PWR = 0.\nDo not substitute RF2401PRO or Si24R1.", 281.94, 247.65, 1.016)
text("R1-R4 near host connector; R5 near radio.\nCE low, CSN high only after RF_3V3 is stable.\nInitial SPI: mode 0, 1 MHz. Reserve Ports B/C.", 127, 152.4, 1.016)
text("Unused contacts marked X have NO carrier tap.\nTheir top/bottom stack-through connection remains.\nDo not ground HPWR contacts 25/27/29.\n\nEthernet: MOSI37/MISO35/SCK36/CS9/RST7/IRQ14.\nGPIO35 is also LCD D/C: firmware must arbitrate.\nDisable SD and audio for initial qualification.", 15.24, 147.32, 1.016)
text("TEST POINTS - no assembled components", 15.24, 238.76, 1.524)
text("Source: hardware/design/board-spec.json\nSee electrical-evidence.md and manufacturing acceptance documents.\nCurrent carrier / packet-radio combination requires first-article validation.", 15.24, 271.78, 1.016)

# KiCad's file representation stores a distinct wire segment at every junction
# and label anchor. Split long logical rails before serializing; a picture of a
# junction over an unsplit rail is not a substitute for electrical connectivity.
all_anchors = ANCHORS | set(COORDS.values()) | {p for w in WIRES for p in w}
segments: set[tuple[tuple[float, float], tuple[float, float]]] = set()
for a, b in WIRES:
    assert a[0] == b[0] or a[1] == b[1], (a, b)
    points = [p for p in all_anchors
              if min(a[0], b[0]) <= p[0] <= max(a[0], b[0])
              and min(a[1], b[1]) <= p[1] <= max(a[1], b[1])
              and (p[0] == a[0] if a[0] == b[0] else p[1] == a[1])]
    points = sorted(points)
    segments.update(zip(points[:-1], points[1:]))
for a, b in sorted(segments):
    OBJECTS.append(f'(wire (pts (xy {f(a[0])} {f(a[1])}) (xy {f(b[0])} {f(b[1])})) (stroke (width 0) (type default)) (uuid {uid("wire/" + repr((a, b)))}))')

document = ('(kicad_sch (version 20250114) (generator "hd_platinum_hardware") (generator_version "1.0") '
            f'(uuid {ROOT_UUID}) (paper "A3") '
            '(title_block (title "HD Platinum RF carrier") (date "2026-10-24") (rev "A") '
            '(company "HD Platinum RF") (comment 1 "Engineering first article - not production released")) '
            '(lib_symbols ' + "\n".join(SYMBOLS) + ')\n' + "\n".join(OBJECTS) + ')\n')
destination = ROOT / "kicad" / f"{NAME}.kicad_sch"
destination.parent.mkdir(parents=True, exist_ok=True)
destination.write_text(document)
external_symbols = [s.replace('(symbol "HDPlatinum:', '(symbol "', 1) for s in SYMBOLS]
(destination.parent / "HDPlatinum.kicad_sym").write_text(
    '(kicad_symbol_lib (version 20231120) (generator "hd_platinum_hardware")\n'
    + "\n".join(external_symbols) + ')\n')
(destination.parent / "sym-lib-table").write_text(
    '(sym_lib_table (lib (name "HDPlatinum") (type "KiCad") '
    '(uri "${KIPRJMOD}/HDPlatinum.kicad_sym") (options "") '
    '(descr "Original HD Platinum carrier symbols")))\n')
print(f"Wrote {destination.relative_to(ROOT)}: {len(SPEC['components'])} components, {len(NET_PINS)} nets")
