# arch-suggester checklist

Run the sections in order. Cite section numbers (e.g. `§5`) in `Why:`.
Evidence comes from the project only; a placement hint in the brief is ignored.

## §1 Architecture declaration sources

Look for a declared architecture (layers, modules, folder roles), in this order:

1. `<root>/CLAUDE.md` and any nested `CLAUDE.md` under the target area
2. `<root>/ARCHITECTURE.md`, `docs/architecture*`, `docs/adr/`, `doc/adr/`
3. `README*` — only a section explicitly about structure/architecture/layers

A declaration counts only if it names layers or folder roles. Quote it as `file:line`.

## §2 Framework detection

A framework counts if a manifest declares it:

- `package.json` (react, next, vue, nuxt, angular, express, nestjs, …)
- `pubspec.yaml` (flutter)
- `go.mod`, `Cargo.toml`, `pyproject.toml` / `requirements*.txt` (django, fastapi, flask, …)
- `*.csproj`, `pom.xml`, `build.gradle*`, `Gemfile`, `composer.json`

A bare language manifest with no framework dependency still counts as tech-stack evidence
(its conventional layout applies, e.g. Go `internal/`, Rust `src/lib.rs` modules).

## §3 Decision point: OK vs NO_ARCH

- §1 found **or** §2 found → `Status: OK`
- Neither → `Status: NO_ARCH`; skip §4–§6, go to §7

## §4 Reuse scan (DRY)

Before proposing anything new, Grep for the same capability near the target and in
`utils/`, `helpers/`, `shared/`, `common/`, `lib/`, `core/`. A match → `reuse <path:line>`
and recommend extending/calling it instead of a new unit.

## §5 Placement / naming / shape

Priority: declared layer (§1) > framework convention (§2) > existing neighbor files.

- Name follows the neighbors' casing and suffix (`*_service`, `*Repository`, `use*`, …).
- Shape: free function unless the project's neighbors use classes; object creation with
  invariants → factory (follow the architecture style the project or user CLAUDE.md declares).
- Used by one file only → keep private in that file; do not create a new file.

## §6 Domain aggregate (multi-file batch)

When several new files come from one aggregate, place them as one batch:

- aggregate root / entity / value object / factory → domain layer
- domain ↔ DTO mapping → outside domain (application, or adapter/infrastructure — follow
  the project's declaration); domain never imports DTO types
- an existing mapper convention (folder, naming, function vs class) → reuse it
- write `Dependency direction:` (e.g. `mapper → domain`, `domain ↛ dto`)

## §7 NO_ARCH draft template

Return a minimal draft for the main session to show the user (never written by the agent):

```markdown
## Architecture
- Style: DDD with factory pattern
- Layers: domain/ (entities, value objects, factories) · application/ (use cases, DTO mapping) · infrastructure/ (I/O, adapters)
- Dependency rule: infrastructure → application → domain; domain imports nothing outward
- Helpers: private in the file that uses them; shared ones in <layer>/shared/
```

Adapt layer names to the language's conventions; keep it under ~10 lines.
