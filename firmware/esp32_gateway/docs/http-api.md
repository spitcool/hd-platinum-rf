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
| `GET /api/shades` | `shades[]` with `id`, `room_id`, `room`, `name`, `position`, `observed_position`, `enabled`, `features`; also status fields. |
| `GET /api/rooms` | `rooms[]`: ID, name, product code. |
| `GET /api/scenes` | `scenes[]`: ID, name, member shade IDs. |
| `GET /api/inventory` | Full supported legacy snapshot in `records[]`, without connection prefixes. |
| `GET /api/status` | Backend, busy/storage flags, delivery, service settings, latest operation ID/status. |
| `GET /api/settings` | `{ "tcp522": true, "http": true, "web": true }`. |
| `PATCH /api/settings` | One or more boolean fields from the above object; persisted before response. No operation request ID required. |
| `POST /api/positions` | `{ "shade": 0, "position": 128, "request_id": "unique-request-id" }`. |
| `POST /api/sync` | `{ "shade": 0, "request_id": "unique-request-id" }`. |
| `POST /api/jog` | Same fields as Sync. |
| `POST /api/scenes` | `{ "scene": 0, "request_id": "unique-request-id" }`. |
| `POST /api/command` | `{ "command": "$dat", "request_id": "unique-request-id" }`; also supports complete setup/scene/schedule transactions from the coverage matrix. |

`position` is a requested raw value 0–255, with 0 closed and 255 open for the
primary channel. `null` means no requested value. `observed_position` is always
`null`: radio feedback is not implemented. `features` is the explicit grant bit
mask, not an inference from product type. `enabled` describes the primary grant;
RF qualification and radio availability can still prevent submission.

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
  --data '{"shade":0,"position":128,"request_id":"shade-zero-half-0001"}'

curl --fail-with-body -X PATCH "http://$GATEWAY_IP:8077/api/settings" \
  -H "Authorization: Bearer $GATEWAY_TOKEN" \
  -H 'Content-Type: application/json' --data '{"tcp522":false}'
```

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
Map 0–100 percent to 0–255 with rounding if building a cover entity. Label its
position as requested/optimistic; do not present it as sensed motor state.
Refresh numeric target IDs after deleting rooms or shades. A full custom cover
integration, setup flow and durable operation history remain follow-up work.
