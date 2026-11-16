<!-- SPDX-FileCopyrightText: 2026 Christopher Spitler -->
<!-- SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later -->

# Local HTTP API and Home Assistant

Base URL: `http://DEVICE_IP:8077`. All `/api/` endpoints require
`Authorization: Bearer TOKEN`. Configure the token in the ignored private header;
use at least 32 random characters. POST and PATCH require `Content-Type:
application/json` and a single `Content-Length`. HTTP/1.1 only, one request per
connection, no chunked encoding or pipelining. Use the device's IPv4 address,
not an arbitrary host alias. There is no CORS access or token query parameter.

`GET /` serves the web interface when enabled. `GET /health` is an unauthenticated
health summary within the allowed client subnet. All inventory and control
endpoints require the bearer token. The HTTP service can be disabled independently
of TCP 522. Setting `web=false` hides the page but leaves authenticated API access.

| Method and endpoint | Body / result |
| --- | --- |
| `GET /api/shades` | `shades[]` with identity/name/product, compatibility primary-position fields, grants, backend support and per-feature `controls[]`; see below. |
| `GET /api/rooms` | `rooms[]`: ID, name, product code. |
| `GET /api/scenes` | `scenes[]`: ID, name, member shade IDs. |
| `GET /api/inventory` | Full supported legacy snapshot in `records[]`, without connection prefixes. |
| `GET /api/status` | Backend, admitted/qualified/bench feature masks, busy/storage flags, unverified delivery, `full_compatibility=false`, service settings and latest operation ID/status. |
| `GET /api/settings` | `{ "tcp522": true, "http": true, "web": true }`. |
| `PATCH /api/settings` | One or more boolean fields from the above object; persisted before response. No operation request ID required. |
| `POST /api/positions` | One `shade` or `room`, optional `feature` (default 4), and either raw `position` 0–255 or `endpoint` `"open"`/`"close"`; also `request_id`. |
| `POST /api/sync` | `{ "shade": 0, "request_id": "unique-request-id" }`. |
| `POST /api/jog` | Same fields as Sync. |
| `POST /api/scenes` | `{ "scene": 0, "request_id": "unique-request-id" }`. |
| `POST /api/command` | `{ "command": "$dat", "request_id": "unique-request-id" }`; also supports complete setup/scene/schedule transactions from the coverage matrix. |

`position` is a requested raw byte, not a travel percentage or a universal
open/close direction. `null` means no requested value. `observed_position` is
always `null`; radio feedback is not implemented. `features` is the persisted
installation grant mask. `backend_features` is the currently admitted mask;
`native_qualified_features` and `native_bench_features` distinguish qualification
from temporary bench permission. Backend names are `simulated`, `repeater-radio`
and `native-radio`. All delivery remains unverified.

Status includes `native_preparation` (0 none, 1 RF wake, 2 command control) and
`native_preparation_frames`. These are read-only build settings for optional
primary-position bench experiments, not HTTP request options or qualification.
Both default to zero. See [radio qualification](radio-qualification.md#optional-wake-preparation).

Each shade's `controls[]` contains the supported product features among 4, 18,
7, 19 and 10. Every entry has `feature`, `label`, `granted`, `backend_supported`,
`available`, `requested_value`, `request_status`, `role`, `endpoint_mapping`, `open_value` and
`close_value`. Role codes are 0 unknown, 1 lift, 2 top rail, 3 bottom rail.
Endpoint codes are 0 unknown, 1 open at raw 0, 2 open at raw 255. Unknown endpoint
values are `null`. Physical mappings are installation facts stored for features
4 and 18; product codes never supply them automatically. `enabled` is the
compatibility primary-control availability field; `position` remains its raw
requested value. Radio readiness/busy/storage can still prevent submission.

Each shade also exposes nullable `last_requested_feature`. A control's
`request_status` is `latest`, `earlier`, `unknown_order` or `never_requested`.
Per-feature values are request history, not simultaneous physical rail
coordinates. Only the known latest request is emitted in the shade's LAN
inventory `$cp` record; ambiguous migrated history emits none until a new
request establishes order. The API does not invent companion-rail values or
position feedback for coupled mechanisms.

Raw requests may select features 4, 18, 7, 19 or 10, subject to product support,
grants and the active backend. Feature 10 accepts only preset value 7; its motor
meaning is unqualified. The native candidate admits only 4, 12 and 18, and
rejects Sync/enrollment. Tilt and preset controls work in simulation only.
An endpoint request requires a known mapping and cannot also supply `position`.
A room request validates every member; endpoint values are resolved separately
per shade, so different raw directions can share an Open request. It does not
send a combined RF group mask. Unavailable controls or unknown endpoints return
409 without a submission.

Native bench images boot disarmed. Their masks can be armed for at most 60
seconds through local USB `rf-test`; HTTP cannot open that window or create
persisted grants. Expiry/disarm cancels remaining native packets. A packet
already started may finish; no automatic retry follows.

POST responses contain `request_id`, `status`, `backend`, `delivery`, `records[]`
and `operation`. An accepted radio/simulation operation initially returns HTTP
200 with `status="submitted"`; this is admission, not success. Poll `/api/status`
and match `operation.id`. Terminal states are `simulated`,
`completed_unverified`, or `failed`. A later operation replaces the latest status;
repeating the original POST with the same request ID retrieves its cached result
while retained. A cached terminal failure returns HTTP 502. Completed metadata
requests use `processed`; rejected commands normally return HTTP 409. Malformed
HTTP/JSON, missing authorization, media type and oversized requests have the
corresponding 400/401/415/413 errors.

Request IDs are 8–64 ASCII letters, digits, hyphens or underscores. Reuse the
same ID and command on a transport retry; using an ID with different command
bytes returns 409. The retry cache holds at most 16 receipts and about 64 KiB,
**only until reboot or eviction**. It is not durable exactly-once delivery.
Reconcile requested state after an ambiguous reboot/disconnection rather than
blindly sending a new ID. No automatic client retry is required by this API.

`/api/command` validates the complete transaction on detached state before
executing it, so incomplete names or missing `$rls` cannot partially apply a
prefix. A hardware/storage failure during an otherwise valid multi-command
transaction can still leave earlier edits committed; physical work is never
rolled back. Use one logical transaction per HTTP request.

## Examples

Keep tokens in your shell environment, not checked-in scripts:

```sh
curl --fail-with-body "http://$GATEWAY_IP:8077/api/shades" \
  -H "Authorization: Bearer $GATEWAY_TOKEN"

curl --fail-with-body "http://$GATEWAY_IP:8077/api/positions" \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -H 'Content-Type: application/json' \
  --data '{"shade":0,"feature":4,"position":128,"request_id":"shade-zero-raw128-0001"}'

curl --fail-with-body -X PATCH "http://$GATEWAY_IP:8077/api/settings" \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -H 'Content-Type: application/json' --data '{"tcp522":false}'
```

For a mapped secondary rail, use `{"shade":0,"feature":18,"endpoint":"open",
"request_id":"shade-zero-secondary-open-0001"}`. For a room, replace `shade`
with `room`; do not supply both. These examples require the corresponding
product support, mapping, grant and backend permission.

Disabling HTTP returns the saved settings and closes HTTP afterward. Recover
with USB command `services 1 1 1`. Pending operations still complete.

## Home Assistant starting point

This is a REST interface suitable for a Home Assistant integration, not a
bundled custom integration or MQTT discovery service. The following uses Home
Assistant's documented [RESTful Command](https://www.home-assistant.io/integrations/rest_command/)
and [RESTful sensor](https://www.home-assistant.io/integrations/rest/) integrations.
It has not been exercised against a running Home Assistant installation.

In `secrets.yaml`, store the **whole header value**:

```yaml
platinum_authorization: "Bearer REPLACE_WITH_YOUR_RANDOM_TOKEN"
```

Replace the documentation-only IP below with the gateway's address, and allow
Home Assistant's subnet in the firmware configuration:

```yaml
rest:
  - resource: "http://192.0.2.10:8077/api/shades"
    headers:
      Authorization: !secret platinum_authorization
    scan_interval: 30
    sensor:
      - name: Platinum gateway shades
        value_template: "{{ value_json.shades | count }}"
        json_attributes:
          - shades
          - backend
          - delivery

rest_command:
  platinum_position:
    url: "http://192.0.2.10:8077/api/positions"
    method: POST
    content_type: "application/json"
    headers:
      Authorization: !secret platinum_authorization
    payload: >-
      {{ {"shade": shade | int, "position": position | int,
          "request_id": request_id} | to_json }}
```

Call `rest_command.platinum_position` with `shade`, `position` and a newly
allocated `request_id` for each intended action. Preserve that ID for any retry.
Use the selected control's verified `open_value`/`close_value` direction before
mapping a cover percentage into a raw byte. A linear raw conversion is not a
calibrated physical travel measurement. Leave unknown mappings as raw controls.
Label position as requested/optimistic, not sensed motor state.
Refresh numeric target IDs after deleting rooms or shades. A full custom cover
integration, setup flow and durable operation history remain follow-up work.
