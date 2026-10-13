<!--
SPDX-FileCopyrightText: 2026 Christopher Spitler
SPDX-License-Identifier: CC-BY-SA-4.0 OR AGPL-3.0-or-later
-->

# Contributing

Contributions to code, documentation, protocol notes, and tests are welcome.
Please keep changes reviewable and explain both their source and how they were
tested.

## Contribution terms

You retain copyright in your contribution. Contributions are accepted under
the license or licenses that govern the target file or component (the
"inbound = outbound" rule):

- host software, tests, configuration, and build metadata:
  `AGPL-3.0-or-later`;
- project documentation: `CC-BY-SA-4.0 OR AGPL-3.0-or-later`; and
- future project-authored firmware in its separate component:
  `GPL-2.0-or-later`, subject to dependency compatibility review.

See [LICENSING.md](LICENSING.md) before adding a new component or third-party
material. New files should carry an appropriate SPDX copyright and license
identifier when their status is not already unambiguously covered by the
component policy.

Every commit must be signed off under the exact Developer's Certificate of
Origin 1.1 in [DCO](DCO). Add the certification with:

```sh
git commit -s
```

This adds a trailer in the following form:

```text
Signed-off-by: Your Name <you@example.com>
```

The sign-off must use a name and email address by which you can be identified.
The project does not require a copyright assignment or CLA and does not request
a separate, broad relicensing grant.

## Provenance

- Submit work you wrote or have the right to submit under the target license.
- Identify borrowed or adapted material, its exact source and version, and its
  license. Update [CREDITS.md](CREDITS.md) when appropriate.
- Do not copy code or prose from unlicensed forum attachments, vendor manuals,
  restricted materials, or incompatible projects.
- Clearly distinguish independently observed protocol facts from quoted or
  adapted expression, and record a reproducible observation or public source.
- Do not submit material obtained under an NDA or other confidentiality duty.

## Security and privacy

Test only devices, radio equipment, and networks you are authorized to use.
Never commit credentials, private keys, tokens, personal data, device serial
numbers, household identifiers, exact locations, or unsanitized packet/log
captures. Prefer synthetic fixtures and redact identifiers before sharing
diagnostic output.

Do not publish details of a suspected security vulnerability in an issue. Use
GitHub private vulnerability reporting when it is available; otherwise open a
minimal issue asking the maintainers for a private contact channel without
including vulnerability details.

## Testing and pull requests

Follow [docs/testing.md](docs/testing.md) for the current test procedure. For
Python-only changes, run at least:

```sh
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

In the pull request, summarize the behavior change, provenance, tests run, and
any hardware or protocol assumptions. Keep captures and local test notes out of
the commit unless they are intentionally sanitized, licensed, and needed as a
reviewable fixture.
