<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Build your own ESP32 gateway

[Back to the project](../README.md)

The gateway firmware targets the **M5Stack CoreS3 / CoreS3 SE (ESP32-S3)**.
It provides a touchscreen, local web interface and Platinum-compatible network
services, with Wi-Fi or wired Ethernet builds. The planned appliance uses the
CoreS3 SE and a custom radio carrier.

**The CoreS3/NiceRF appliance is unassembled and unqualified.** The firmware
implements the gateway services, feature-aware controls and a finite native
radio candidate. You can build simulation and explicitly disarmed bench images,
but no image has been flashed onto or tested with this stack. Successful SDR
shade tests do not qualify the NiceRF hardware or establish full compatibility.

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
| `GATEWAY_RF_ENABLED`, `GATEWAY_RF_QUALIFIED` | Leave both `false` for ordinary simulation builds |
| `GATEWAY_RF_NATIVE`, `GATEWAY_RF_BENCH` | Default `false`; the dedicated native test environments select these explicitly |
| `GATEWAY_RF_NATIVE_QUALIFIED_FEATURES` | Leave `0`; this is measured per-feature qualification, not a general enable switch |

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

| Environment | Connection and default radio behavior |
| --- | --- |
| `cores3` | Wi-Fi; simulation with the example configuration |
| `cores3_ethernet` | Base LAN v1.2 Ethernet; simulation with the example configuration |
| `cores3_native_test` | Wi-Fi; native bench candidate, boots disarmed, qualification mask forced to zero |
| `cores3_ethernet_native_test` | Ethernet; same disarmed native bench candidate |

Compile the Wi-Fi build:

```sh
pio run -d firmware/esp32_gateway -e cores3
```

To build the candidate images without uploading:

```sh
pio run -d firmware/esp32_gateway -e cores3_native_test -e cores3_ethernet_native_test
python firmware/esp32_gateway/tools/test_native.py --sanitizers
```

Each environment writes `firmware.bin`, `firmware.elf` and a 16 MB
`firmware.merged.bin` under `firmware/esp32_gateway/.pio/build/ENVIRONMENT/`.
The post-build tool derives application offsets from the selected partition
CSV and checks that individual upload inputs do not overlap NVS. Use the
PlatformIO upload path for an existing installation; a full merged image is a
complete flash image, not a promise to retain stored state. Export the private
inventory before replacing an installation's flash.

The following is the upload procedure for an available CoreS3 using the ordinary
simulation image. It has not been performed on the unassembled appliance.
Connect the board with a USB data cable, then upload and open its serial monitor:

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

The touchscreen and web interface share the same inventory and feature grants.
Select a feature and a raw value; Open/Close requires a verified endpoint
mapping. Raw 0/255 does not universally mean closed/open. Simulated actions
update requested state without transmitting RF. Saved service settings override
the build defaults; the USB command `services 1 1 1` restores TCP, HTTP and web
access if they were disabled. See the
[HTTP API guide](../firmware/esp32_gateway/docs/http-api.md) for integration details.

## Control mappings and stored state

USB `control SHADE FEATURE ROLE OPEN_VALUE` records a verified mapping for
feature 4 or 18. Roles are 0 unknown, 1 lift, 2 top rail and 3 bottom rail.
`OPEN_VALUE` is 0, 255 or 256 for unknown. This changes labels/direction without
granting permission. Product metadata alone does not establish which physical
rail moves. Feature 18 is decimal 18, not hexadecimal 18.

The CRC-protected PGW1 database envelope now stores schema 3, including the
latest requested feature separately from per-feature history. Schema-1 and
schema-2 backups migrate; a single historical entry establishes the latest
request, while multiple entries without chronology remain unknown. Schema-1
physical mappings remain unknown. No requested value becomes measured feedback.
Rebinding invalidates affected mappings, grants and request history. Inventory
backup/import and repeater sequence allocation remain separate.

## Native bench image and remaining RF work

Complete the [hardware acceptance procedure](../hardware/manufacturing/acceptance-test.md)
on the first assembled stack, then follow the
[radio qualification procedure](../firmware/esp32_gateway/docs/radio-qualification.md).
Prefer the wired candidate for initial RF tests. Its supported native candidates
are primary feature 4, Jog feature 12 and secondary feature 18. Startup programs
registers but emits no packet. Persisted shade grants alone cannot transmit:
local USB `rf-test FEATURE_BITMASK` admits selected supported bits for at most
60 seconds; `rf-test 0` disarms and cancels remaining work. It does not grant a
shade, qualify a feature or replay failed work. `command LAN_TRANSACTION` sends
one complete transaction through the same gated engine.

The native planner uses five-byte bodies, per-packet 33/52/71 rotation and
explicit 7,500/1,500 phase counts at nominal 200.5 µs slots. Native transmission
has no repeater sequence requirement. The older 2440 MHz/250 kbps repeater route
retains its separate ordinal reservation and qualification flags.

The actual module's 2 Mbps, no-PCF framing and timing remain unproved.
[Nordic's nRF24L01+ specification](https://www.sparkfun.com/datasheets/Wireless/Nordic/nRF24L01P_Product_Specification_1_0.pdf)
only documents legacy no-PCF interoperability at 1 Mbps/250 kbps; this is an
unresolved compatibility question, not proof of impossibility. Independently
capture the NiceRF output before interpreting a submitted packet as the desired
wire format. Physical shade response must then be qualified separately.

Native Sync/enrollment is rejected pending a distinct longer train, cancellation
and new-binding tests. Tilt features 7/19 and preset feature 10 remain simulation
only. Handheld receive/feedback, complete enrollment and all installed product
behaviors are not delivered by this image. Do not enable qualification bits
merely because compilation or host tests pass.

For firmware tests, simulators, implementation details and licensing, see the
[firmware README](../firmware/esp32_gateway/README.md).
