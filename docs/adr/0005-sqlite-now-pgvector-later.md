# 0005. SQLite now, Postgres + pgvector later

Status: accepted, 2026-10-07

## Context
Reviewers must be able to clone the repo and run it with one command, without an API key or Docker (D5). The expected volume is small (assumption A2: under about 10K requests). Brute-force cosine search in numpy over 10K × 384 float32 vectors (about 15 MB) takes milliseconds.

## Decision
- SQLite in WAL mode via SQLModel, in a single process: the API plus the worker loop.
- Vectors are stored as float32 BLOBs in the `embedding` table and searched with brute-force numpy cosine, held in memory and updated on write.
- No sqlite-vec and no approximate-nearest-neighbour (ANN) index.
- Move to Postgres + pgvector when any of these becomes true:
  - more than one API or worker process;
  - more than about 100K vectors;
  - more than one tenant.

## Alternatives rejected
- **Postgres + pgvector now.** The right production target, but it needs Docker, migrations and a CI service, so it costs setup time and the one-command offline run.
- **sqlite-vec.** One more native extension, for a speed-up we don't need below about 100K vectors.
- **A separate vector DB** (Qdrant, Chroma). A second datastore to keep consistent with the first.

## Consequences
- Only one process writes, so worker throughput is limited. That's acceptable at this volume.
- The move to Postgres is mostly a change of database URL, because SQLModel abstracts the engine. Vector search moves to pgvector, and the retrieval interface stays the same.
- The in-memory vector matrix must stay consistent with the table. It is rebuilt at startup and updated in the same code path that writes embeddings.
