#!/usr/bin/env python3
"""Apply the reviewed initial prerequisite order to existing stream buffers."""
from __future__ import annotations

import json
from datetime import date, timedelta
from cardlib import all_cards

ORDER = {
    "linux": ["linux-du-summary-001", "linux-find-name-type-001", "linux-grep-context-001", "linux-pipeline-stdout-001", "linux-tar-create-001", "linux-type-command-kind-001", "linux-redirection-streams-001", "linux-awk-fields-001", "linux-uniq-adjacent-001", "linux-less-follow-001", "linux-time-measures-001", "linux-ss-listeners-001", "networking-dns-trace-001", "linux-nohup-session-001"],
    "ai": ["ai-embedding-similarity-001", "ai-temperature-not-confidence-001", "ai-class-imbalance-accuracy-trap-001", "ai-preprocessing-train-only-fit-001", "ai-classification-threshold-tradeoff-001", "ai-probability-calibration-001", "ai-rag-chunk-boundary-overlap-001", "ai-structured-output-schema-validation-001", "ai-data-drift-vs-concept-drift-001", "ai-train-serving-feature-skew-001", "ai-prompt-model-version-tracing-001", "ai-retrieved-content-untrusted-001", "ai-tool-retry-idempotency-001", "review-ai-reliability-retrieval-001"],
    "dev": ["python-pathlib-path-composition-001", "python-with-open-context-manager-001", "git-diff-cached-before-commit-001", "python-mutable-default-argument-001", "git-restore-staged-keep-worktree-001", "docker-build-cache-ordering-001", "review-dev-python-git-docker-001", "python-explicit-exception-chaining-001", "docker-healthcheck-exit-status-001", "dockerignore-build-context-001", "git-reflog-find-lost-commit-001", "git-force-with-lease-001", "docker-exec-form-signal-handling-001", "review-dev-container-signals-001"],
    "mlops": ["docker-image-digest-pinning-001", "mlops-model-artifact-checksum-001", "docker-runtime-non-root-user-001", "mlops-training-run-lineage-001", "ai-request-bounded-concurrency-001", "docker-read-only-root-filesystem-001", "review-mlops-image-identity-001", "docker-buildkit-secret-mount-001", "ai-end-to-end-deadline-propagation-001", "mlops-model-canary-rollback-criteria-001", "mlops-feature-point-in-time-join-001", "ai-model-dependency-circuit-breaker-001", "ai-tool-call-server-authorization-001", "review-mlops-release-reliability-001"],
}

paths = {card["id"]: (path, card) for path, card in all_cards()}
start = date(2026, 8, 8)
beginner_overrides = {
    "docker-image-digest-pinning-001",
    "mlops-model-artifact-checksum-001",
    "docker-runtime-non-root-user-001",
}
for stream, ids in ORDER.items():
    missing = [card_id for card_id in ids if card_id not in paths]
    if missing:
        raise SystemExit(f"Cannot resequence {stream}; missing IDs: {missing}")
    for index, card_id in enumerate(ids, 1):
        path, card = paths[card_id]
        card["sequence"] = index
        card["date"] = (start + timedelta(days=index - 1)).isoformat()
        if card_id in beginner_overrides:
            card["difficulty"] = "beginner"
        path.write_text(json.dumps(card, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
print("Resequenced four 14-card streams from foundations toward advanced practice.")
