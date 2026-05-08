# Wiki Schema

## 1. Knowledge Base Root

Each knowledge base is stored under:

`viking://resources/<kb>/`

Required structure:

- `raw/` — source materials
- `wiki/` — generated wiki pages
- `wiki/index.md` — canonical index of all wiki pages
- `wiki/overview.md` — high-level summary of the knowledge base
- `wiki/log.md` — chronological operation log
- `wiki/sources/` — source pages derived from raw materials
- `wiki/entities/` — entity pages
- `wiki/concepts/` — concept pages
- `wiki/syntheses/` — saved query syntheses
- `graph/` — graph outputs such as `graph.json` and `graph.html`

## 2. Page Types

### 2.1 Source Page
Purpose: summarize one raw source and extract key entities, concepts, claims, and links.

Location:
`wiki/sources/<slug>.md`

### 2.2 Entity Page
Purpose: describe a concrete named entity such as person, company, project, paper, library, tool, dataset, or organization.

Location:
`wiki/entities/<slug>.md`

### 2.3 Concept Page
Purpose: describe an abstract concept, method, workflow, architecture, principle, or recurring theme.

Location:
`wiki/concepts/<slug>.md`

### 2.4 Synthesis Page
Purpose: save a query-driven synthesized answer derived from multiple wiki pages.

Location:
`wiki/syntheses/<slug>.md`

## 3. Naming Rules

- Use lowercase kebab-case for filenames.
- Keep filenames stable once created.
- Prefer short but specific names.
- Use one canonical page per main concept/entity whenever possible.

## 4. Linking Rules

- Use `[[wikilinks]]` for internal page references.
- Prefer linking to canonical pages rather than repeating explanations.
- Every page should link outward to at least one related page unless it is a bootstrap stub.

## 5. Required Page Template

Each wiki page should include:

- Title
- Type
- Summary
- Main content
- Related links
- Source references if applicable

## 6. Index Rules

`wiki/index.md` is the canonical directory of wiki pages.

It should group entries under:
- Sources
- Entities
- Concepts
- Syntheses

Every real wiki page should appear in `index.md`.

## 7. Overview Rules

`wiki/overview.md` should summarize:
- main topics
- important entities
- major concepts
- known gaps
- recent changes

It should be concise but updated after major ingest operations.

## 8. Log Rules

`wiki/log.md` records chronological actions such as:
- source ingested
- page created
- page updated
- synthesis saved
- structural refactor

Each entry should include:
- timestamp
- action type
- target pages
- short note

## 9. Ingest Workflow

When ingesting a raw source:

1. Read the raw source.
2. Read relevant context from `wiki/index.md`, `wiki/overview.md`, and related pages.
3. Create or update one source page.
4. Create or update related entity pages.
5. Create or update related concept pages.
6. Update `wiki/index.md`.
7. Update `wiki/overview.md`.
8. Append a record to `wiki/log.md`.

## 10. Query Workflow

When answering a query:

1. Read `wiki/index.md`.
2. Select relevant pages.
3. Read those pages.
4. Synthesize an answer grounded in the wiki.
5. Optionally save the result to `wiki/syntheses/`.
6. If saved, update `wiki/index.md` and `wiki/log.md`.

## 11. Health Workflow

Health checks should verify:
- required directories exist
- required root pages exist
- index entries point to real pages
- key pages are not empty
- source pages are reflected in the log

## 12. Graph Workflow

Graph outputs are optional.
They may be generated from explicit `[[wikilinks]]` and inferred semantic edges.
Only final graph artifacts should be written to remote storage.
Temporary graph caches should remain local.