# Synthetic IODA contract cases

These fixtures were written from scratch for WICI on 2026-10-18 using the
field contract consumed by `src/wici/ioda.py` and the requirements of
`tests/test_ioda.py`. They are not downloaded API responses, anonymized
measurements, or copies of the provider's OpenAPI document. Their original
test content is covered by WICI's MIT license.

Every JSON envelope contains `metadata.synthetic: true` and our own notice,
`Synthetic WICI test data (MIT); not an IODA response.`, in the `copyright`
field so tests still verify preservation of source-notice metadata. Network names,
measurements, scores and timestamps are invented. ASN `64512` identifies a
fictional private-use network named `WICI synthetic network`, not an observed
operator. Country `PL`, the sixteen region code/name pairs in WICI's `REGIONS`
mapping, datasource identifiers and unit labels are retained solely to exercise
the existing parser contract. Region `999999` is a fictional unmapped case.
The fixed test clock is 2026-10-17 08:00 UTC; no value describes connectivity
in Poland at that time.

| File | Purpose |
|---|---|
| `country.json` | Country envelope with an empty, valid `attrs` object. |
| `regions.json` | Sixteen mapped regions with `country_code=PL`, plus one fictional region without geometry. Tests also reject a changed name/country and missing `attrs`. |
| `asn.json` | Fictional ASN metadata; an ASN never acquires province geometry. |
| `datasources.json` | The three signal identifiers and unit labels accepted by WICI. |
| `events_ioda.json` | One invented five-minute event with a critical alert at the start and a normal alert at the end. Tests remove the final alert to verify an unconfirmed end and update the query boundary. |
| `alerts.json` | The same invented critical/normal pair as independent alert records. |
| `events.json` | Minimal CODF-shaped negative case with `status=0`; deliberately lacks the supported IODA event structure and must not become evidence of recovery. It is not a full CODF specification. |
| `signals.json` | Four country samples `[8, null, 0, 6]` on a 300-second grid, preserving the distinction between no measurement and a measured zero. |
| `signals_multi.json` | Two nested region groups with different lengths, including `null` and zero. |

The tests inject malformed envelopes, changed units, invalid event rows,
pagination, HTTP errors, timeouts and rate limits in memory. Mock HTTP calls
use the application's endpoint to test request construction but never reach
the network. Synthetic metadata must survive storage as provenance. These
cases exercise offline parser, collector and persistence behavior; they are
not independent evidence that the remote API still follows the contract.

The former downloaded responses, OpenAPI copy, probe provenance and unused
ASN catalogue were removed from the current tree. The original repository retains its earlier history; that history is not
included in this clean repository. The application demo is a
separate synthetic dataset and does not load these fixtures.
