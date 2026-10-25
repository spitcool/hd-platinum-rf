<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Build your own ESP32 gateway

[Back to the project](../README.md)

The gateway firmware targets the **M5Stack CoreS3 / CoreS3 SE (ESP32-S3)**.
It provides a touchscreen, local web interface and Platinum-compatible network
services, with Wi-Fi or wired Ethernet builds. The planned appliance uses the
CoreS3 SE and a custom radio carrier.

**The project is currently confirming the RF protocols and designing the hardware
implementation.** You can compile the firmware and try its simulated controls;
the physical gateway still needs hardware and RF qualification. A successful
build does not establish that it will operate your shades.

## Bill of materials

For initial Wi-Fi development with RF disabled, use a CoreS3 or CoreS3 SE and
a USB-C **data** cable to your computer. The firmware simulates commands without
the radio carrier. The Ethernet build also needs the Base LAN v1.2.

The planned complete appliance has these parts:

| Quantity | Part | Purpose |
| ---: | --- | --- |
| 1 | M5Stack CoreS3 SE **K128-SE** | ESP32-S3 controller and touchscreen |
| 1 | M5Stack Base LAN v1.2 **K012-B-V12** | W5500 Ethernet and base enclosure |
| 1 | M5Stack Module13.2 Proto **M032** | Radio enclosure; replace its perfboard with the custom carrier |
| 1 | Project revision-A radio carrier PCBA | Includes the NiceRF **RF2401F20**, regulator, M-Bus socket and RF connector |
| 1 | Taoglas **CAB.628** | Internal coax and RP-SMA bulkhead |
| 1 | Taoglas **GW.11.A153** | External 2.4 GHz antenna |
| 1 | Raspberry Pi **SC0218** USB-C supply | Planned appliance power supply |
| 1 set | Stack fasteners, coax strain relief and enclosure bulkhead modification | Final dimensions and routing require a physical fit check |
| 1 | Cat5e or better RJ45 patch cable | Wired network connection |

Use the [system BOM](../hardware/manufacturing/system-bom.csv) for appliance
parts and the [carrier PCB BOM](../hardware/manufacturing/bom.csv) for the parts
fitted to the board. The carrier row above already includes those PCB components.
The [illustrated assembly guide](../hardware/manufacturing/final-assembly.md)
shows the stack; [hardware documentation](../hardware/README.md) covers the CAD
and manufacturing package. Revision A remains an engineering first article.

The separate [RF validation bench BOM](bom.md) lists SDRs, receivers and test
equipment used to research and qualify the protocols.

The supplied firmware depends on CoreS3 hardware, pin assignments, display and
power management. A generic ESP32 development board needs a hardware port;
changing the PlatformIO board name alone is not sufficient.

## Set up the build tools

Use Python 3.10 or later. Clone the repository, or use your existing checkout:

```sh
git clone https://github.com/spitcool/hd-platinum-rf.git
cd hd-platinum-rf
```

Run the remaining commands from the repository root:

```sh
python3 -m venv .venv
. .venv/bin/activate
python -m pip install platformio==6.1.18
export PLATFORMIO_CORE_DIR="$PWD/tmp/esp32-platformio"
```

PlatformIO installs the toolchain and libraries specified in
[platformio.ini](../firmware/esp32_gateway/platformio.ini). The first build needs
network access. In a new terminal, activate the virtual environment and set
`PLATFORMIO_CORE_DIR` again before building.

## Configure your device

Create the private configuration header; `-n` preserves an existing one:

```sh
cp -n firmware/esp32_gateway/include/gateway_config.example.h \
  firmware/esp32_gateway/include/gateway_config.h
```

Edit `firmware/esp32_gateway/include/gateway_config.h`:

| Setting | Value to supply |
| --- | --- |
| `GATEWAY_WIFI_SSID`, `GATEWAY_WIFI_PASSWORD` | Your Wi-Fi credentials, for the Wi-Fi build |
| `GATEWAY_CLIENT_NETWORK`, `GATEWAY_CLIENT_MASK` | The trusted IPv4 subnet allowed to access either network build; replace the example with your own network |
| `GATEWAY_API_TOKEN` | At least 32 random characters for the web interface and HTTP API |
| `GATEWAY_RF_ENABLED`, `GATEWAY_RF_QUALIFIED` | Leave both `false` for initial development |

Generate a token locally with:

```sh
python -c 'import secrets; print(secrets.token_hex(32))'
```

The header is ignored by Git. Keep it and compiled images containing your
credentials private. A blank Wi-Fi SSID leaves Wi-Fi unconfigured, a blank token
disables authenticated API access, and an unset client subnet disables network
access. TCP 522 is unauthenticated and HTTP uses plain local-network connections;
keep both on your trusted LAN.

## Compile and upload

Choose the build for your network connection:

| Environment | Connection |
| --- | --- |
| `cores3` | Wi-Fi |
| `cores3_ethernet` | Base LAN v1.2 wired Ethernet |

Compile the Wi-Fi build:

```sh
pio run -d firmware/esp32_gateway -e cores3
```

Connect the CoreS3 to your computer with the USB data cable, then upload and
open its serial monitor:

```sh
pio run -d firmware/esp32_gateway -e cores3 --target upload
pio device monitor -d firmware/esp32_gateway -e cores3 --baud 115200
```

For the wired build, use `-e cores3_ethernet` in all three commands and connect
the Base LAN to your network. If port detection is ambiguous, run
`pio device list`, then add `--upload-port PORT` to the upload command and
`--port PORT` to the monitor command, replacing `PORT` with your device's port.
Exit the monitor with Ctrl-C before another upload.

Power through CoreS3 USB-C and leave the LAN base's separate DC input
disconnected. Keep the SD socket empty and other accessories disconnected for
the current hardware configuration. Follow the assembly and acceptance documents
before powering a newly assembled carrier.

## First startup

1. In the serial monitor, send `status` followed by Enter. Check for
   `storage=ok`, `network=up` once connected, and `mode=simulation`.
2. Find the device's IPv4 address in your router's DHCP client list and open
   `http://DEVICE_IP:8077/` from the allowed subnet. Use the token from your
   private configuration header.
3. Populate rooms and shades using the legacy app or the API. Follow
   [Configure and provision](../firmware/esp32_gateway/README.md#configure-and-provision)
   for a fictional room/shade example and the USB grant commands. New shades
   start with no operation grants, so controls remain disabled until granted.

The touchscreen and web interface share the same inventory. Simulated actions
update requested state without transmitting RF. Saved service settings override
the build defaults; the USB command `services 1 1 1` restores TCP, HTTP and web
access if they were disabled. See the
[HTTP API guide](../firmware/esp32_gateway/docs/http-api.md) for integration details.

## Before controlling real shades

The ESP32 radio driver has not yet demonstrated shade interoperability on the
physical stack. Complete the
[hardware acceptance procedure](../hardware/manufacturing/acceptance-test.md)
and [radio qualification procedure](../firmware/esp32_gateway/docs/radio-qualification.md)
before enabling physical transmission. Use the wired build for RF qualification,
validated installation bindings and grants, and the next unused RF sequence value.
Do not set the qualified flag merely because compilation succeeds.

For firmware tests, simulators, implementation details and licensing, see the
[firmware README](../firmware/esp32_gateway/README.md).
