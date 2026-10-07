#### dev: baseline (auto ≥ 0.7666, suggest ≥ 0.6508)

| Slice | n | Accuracy | False merges (all links) | False merges (auto) | Recall@1 | Recall@3 | Recall@5 | Bands auto/suggest/new |
|---|---|---|---|---|---|---|---|---|
| all | 62 | 62.9% (39/62, CI 50-74%) | 39.3% (22/56, CI 28-52%) | 0.0% (0/13, CI 0-23%) | 77.3% (34/44, CI 63-87%) | 90.9% (40/44, CI 79-96%) | 95.5% (42/44, CI 85-99%) | 13/43/6 |
| first_appearance | 18 | 27.8% (5/18, CI 12-51%) | 100.0% (13/13, CI 77-100%) | n/a (n=0) | n/a (n=0) | n/a (n=0) | n/a (n=0) | 0/13/5 |
| repeat | 44 | 77.3% (34/44, CI 63-87%) | 20.9% (9/43, CI 11-35%) | 0.0% (0/13, CI 0-23%) | 77.3% (34/44, CI 63-87%) | 90.9% (40/44, CI 79-96%) | 95.5% (42/44, CI 85-99%) | 13/30/1 |

Duplicates: precision 60.7% (34/56, CI 48-72%), recall 77.3% (34/44, CI 63-87%), F1 0.680. Latency per decision (embed + search): p50 9.4 ms, p95 16.0 ms.

Accuracy by similarity bucket: [0.0, 0.5) 100.0% (1/1, CI 21-100%), [0.5, 0.6) 100.0% (1/1, CI 21-100%), [0.6, 0.7) 40.9% (9/22, CI 23-61%), [0.7, 0.8) 68.8% (22/32, CI 51-82%), [0.8, 0.9) 100.0% (6/6, CI 61-100%)
