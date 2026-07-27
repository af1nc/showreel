# statement-password-resolver

**Banks lock their statements with passwords they print in the email.** Financial
institutions encrypt PDF statements with formulaic passwords — birth-date digits, name
fragments, phone-number tails — and every institution invents its own recipe. Automate
ingestion across several and either every extractor rolls its own derivation logic and
drifts, or the recipes live in one resolver with one audit point.

## Try it

```bash
python main.py --demo
```

Stdlib only. The demo derives candidates for three synthetic institutions (each recipe
*shape* is real — this is genuinely what retail banks do), unlocks documents by trying
candidates in order, exercises the legacy-fallback path, and routes a missing-credential
case to "ask the user" instead of raising.

## The interesting part

- **One derivation matrix.** Every institution's recipe in a single reviewable table.
  Password derivation is exactly the kind of logic that must never be duplicated.
- **Candidates, not answers.** Some institutions use different shapes per document
  type; some accounts still answer to a legacy recipe. The resolver returns an ordered
  list; the caller tries them in order and the audit trail records every rejection.
- **The resolver never decrypts.** Plaintext candidates exist only on the call stack,
  flow straight to the decryptor, and are never persisted or logged unmasked.
- **Missing credentials are routing, not failure.** "We don't have Sam's customer
  number" is a product state with a next step, not an exception.
