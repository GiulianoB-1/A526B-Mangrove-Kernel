# P479 explicit single-source repository cutover authorization

Initiated on 2026-11-19, after the user created the empty repository
GiulianoB-1/A526B-Mangrove-Source and confirmed the dedicated
SOURCE_REPO_PAT secret was updated.

Read-only credential test run: 44071181375, attempt 2.
Verified token passed: GET /user HTTP 200, GET destination repository HTTP 200,
and SHA-less, non-mutating source-ref write permission probe HTTP 422.

Frozen source release: p479-verified-source-baseline.
Producer: GitHub Actions run 44038773282, commit
5e6fb4713022f22b417a9e6581cf3c5d9c2b16f5.
Source archive SHA256:
43ecd5698f319328290721c4f79d1dddfe7e8acb30f4ba1c3a47629f2115d9e3.
Original P479 equivalence baseline: run 43638159300.
Independent cutover dry-run: run 44054240616 PASS, 73,771 tracked files,
one Git commit tagged p479-baseline, KernelSU preserved without nested Git.

This is a one-time, fail-closed source migration only. Do not overwrite an
existing nonempty repo; do not flash; do not modify the proof gates; do not
apply P480 until native source baseline verification passes.
