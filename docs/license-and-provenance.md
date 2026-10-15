# License, attribution, and provenance

Voicefolio's source code is Apache-2.0. Catalog inclusion does not relicense upstream recordings. Each voice row carries its own license label, evidence, source repository/revision/path, source size, and SHA-256. Review those fields and the upstream terms for the specific recording before using or redistributing it.

## Fail-closed source curation

Maintained-source builders verify evidence against pinned upstream revisions and preserve complete published rows when their source bytes remain unchanged. They do not infer licenses or attribution from a speaker's name, filename similarity, accent, or neighboring rows. Uncertain rights remain explicit; Voice-Zero files without exact attribution are quarantined with diagnostics rather than catalogued as attributed voices.

Fine Read It reference audio and synthesized demos are different assets. A demo has its own format, URL, size, and SHA-256 and is fetched only when explicitly requested. It does not change the reference voice's license, source digest, or managed identity.

Language and accent are distinct metadata. `und` indicates that language is not authoritatively known. A Voice-Zero accent value that upstream does not verify remains marked unverified and is not converted into a language claim.

## Use and consent

A recording license does not by itself establish consent for voice cloning, impersonation, biometric processing, or every commercial use. Voice likeness and publicity/privacy rights vary by person, jurisdiction, and use case. Users remain responsible for evaluating applicable permissions and restrictions, even when a catalog entry has a permissive file license.

## Integrity is not permission

SHA-256 and pinned source revisions establish which bytes Voicefolio verifies. They do not establish ownership, consent, or suitability for a particular use. Derived renderer WAVs have their own digest and recipe metadata; the managed-reference digest always identifies original source bytes.
