---
schema_version: 2
object_type: release_entry
versioning:
  schema_version: 1
  revision: 1
entry_id: entry-0005
release_version: 0.1.2
kind: quality
summary:
  Improved scheduled source-refresh workflows with release-artifact checks
  and isolated installed-wheel smoke tests
status: accepted
audience: null
scopes: []
source_refs: []
paths:
  - .github/workflows/ci.yml
  - .github/workflows/python-publish.yml
  - .github/workflows/refresh-fine-read-it-catalog.yml
  - .github/workflows/refresh-voice-zero-catalog.yml
  - MANIFEST.in
  - pyproject.toml
  - tools/check_release_artifacts.py
  - tools/smoke_installed.py
  - tests/test_packaging.py
issues: []
prs: []
sources:
  - git:4108e70977fb44803f51fc83c525b9930521de12
contributors:
  - "@holgern"
breaking: false
internal: false
order: 5
---
