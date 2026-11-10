# Project Wycheproof RSA signature vectors (trimmed)

`rsa_pkcs1_sha256_trimmed.json` holds test vectors from
[Project Wycheproof](https://github.com/C2SP/wycheproof), which Deck Lab's
sign-in verifier (`decklab/lib/access.py`, `rsa_sha256_valid`) is checked
against in `decklab/tests/test_access.py` (`WycheproofTests`, story E11-S66).
Nobody who wrote the verifier wrote them, which is the point.

## Source

- Repository: https://github.com/C2SP/wycheproof
- Commit: `e0df04e0c033f2d25c5051dd06230336c7822358` (2025-10-07)
- Files, all RSASSA-PKCS1-v1_5 with SHA-256 (schema `rsassa_pkcs1_verify_schema_v1.json`):
  - `testvectors_v1/rsa_signature_2048_sha256_test.json` (259 tests)
  - `testvectors_v1/rsa_signature_3072_sha256_test.json` (259 tests)
  - `testvectors_v1/rsa_signature_4096_sha256_test.json` (258 tests)

## Licence

Project Wycheproof is licensed under the Apache License, Version 2.0; a copy
is in `LICENSE` beside this file, as that repository gives it. The vectors are
used under that licence. The rest of Deck Lab has its own licence; this folder
keeps Wycheproof's.

## Changes made here

The JSON file is **not** an original Wycheproof file. It was made from the
three files above, on 2026-11-10, by these changes only:

- The three files are joined into one, each under `files` with its original
  path and its original `numberOfTests`.
- Of the 2048-bit file (the size of the keys Cloudflare Access signs with)
  every test is kept. Of the 3072-bit and 4096-bit files, every `valid` and
  `acceptable` test is kept, and of the `invalid` ones the first that carries
  each flag (one per kind of damage); `kept` counts what remains.
- Each test group keeps its `keySize` and its public key as `n` and `e` (the
  original `publicKey.modulus` and `publicKey.publicExponent`, hexadecimal).
  The other encodings of the same key (`publicKeyAsn`, `publicKeyDer`,
  `publicKeyPem`, `keyJwk`) and the group's `sha`, `type` and `source` are dropped.
- Each test keeps `tcId`, `comment`, `flags`, `msg`, `sig` and `result` unchanged.
- The files' `header`, `notes` (the flags' descriptions) and `schema` are dropped.

No message, signature, key, flag or expected result was edited.

## How the tests read the results

`valid` vectors must verify. `invalid` ones must not. `acceptable` ones (a
signature whose DigestInfo leaves out its NULL, which lenient verifiers of old
took) must not either: Deck Lab compares against the one exact encoding.

## Refreshing

Download the three files at a newer commit, apply the same trim, update the
commit above and in the JSON's `commit`, and correct the counts
`WycheproofTests` expects.
