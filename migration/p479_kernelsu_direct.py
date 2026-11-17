#!/usr/bin/env python3
"""Convert the archived ReSukiSU submodule Kbuild to an ordinary source tree.

One-time P479 source migration only. No build gates are weakened. The original
Kbuild is SHA-verified and preserved byte-for-byte in ci/ as source evidence.
The replacement preserves P479's actual compiled KernelSU version, which was
read from the SHA-pinned original P479 vmlinux, without requiring nested .git.
Future P480 versions must be updated by ordinary source commits.
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

ORIGINAL_KBUILD_SHA256 = "08bbd04a5667f54db6ac4ca8bf7ccf4b90187971f0b7e392d667468596de3cf6"
ORIGINAL_P479_KSU_VERSION = 35171
ORIGINAL_P479_KSU_FULL = "v4.2.0-rc3-239e1e88-dirty@ReSukiSU"
HEADER = "REPO_NAME := ReSukiSU\n"
BOUNDARY = "# call subst to process placeholders\n"
REPLACEMENT = """REPO_NAME := ReSukiSU

KDIR := $(KDIR)
KSU_SRC := $(realpath $(dir $(abspath $(lastword $(MAKEFILE_LIST)))))

# P479 reproduces the *original* ReSukiSU submodule's compiled version.
# Original separate git HEAD=239e1e8871b8fcd51a6e5b3002e0ba522fdd99fb.
# Original KSU history: 4,471 commits; built with a dirty-worktree suffix.
# This ordinary kernel source repository has no nested KernelSU/.git.
# A later P480 source commit may deliberately revise these source constants.
KSU_LOCAL_VERSION := 4471
KSU_VERSION := $(shell expr 30000 + $(KSU_LOCAL_VERSION) + 700)
KSU_TAG_NAME := v4.2.0-rc3
KSU_COMMIT_SHA := 239e1e88-dirty
KSU_BRANCH_NAME :=

ifdef KBUILD_EXTMOD
include $(KSU_SRC)/tools/ddk_compatible.mk
endif

"""


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def derive(original: bytes) -> bytes:
    assert digest(original) == ORIGINAL_KBUILD_SHA256, "original KernelSU Kbuild SHA mismatched"
    src = original.decode("utf-8")
    assert src.count(HEADER) == 1, "ReSukiSU Kbuild header missing"
    assert src.count(BOUNDARY) == 1, "ReSukiSU substitution boundary changed"
    start = src.index(HEADER)
    stop = src.index(BOUNDARY, start)
    old = src[start:stop]
    for required in (
        "LOCAL_GIT_EXISTS", "KSU_LOCAL_VERSION :=", "KSU_VERSION :=",
        "KSU_TAG_NAME", "KSU_COMMIT_SHA", "KSU_BRANCH_NAME", "KBUILD_EXTMOD",
    ):
        assert required in old, "missing original Kbuild statement: " + required
    after = src[:start] + REPLACEMENT + src[stop:]
    assert "LOCAL_GIT_EXISTS" not in after, "submodule-only Git blocker remained"
    assert "GIT_BIN :=" not in after, "unexpected inherited Git version command"
    for required in (
        'KSU_VERSION_FULL := $(subst %TAG_NAME%,$(KSU_TAG_NAME),$(KSU_VERSION_FULL))',
        'KSU_VERSION_FULL := $(subst %COMMIT_SHA%,$(KSU_COMMIT_SHA),$(KSU_VERSION_FULL))',
        'ccflags-y += -DKSU_VERSION=$(KSU_VERSION)',
        'ccflags-y += -DKSU_VERSION_FULL=\\\"$(KSU_VERSION_FULL)\\\"',
    ):
        assert required in after, "KernelSU compiled-version contract changed: " + required
    assert 30000 + 4471 + 700 == ORIGINAL_P479_KSU_VERSION
    assert "v4.2.0-rc3-239e1e88-dirty@ReSukiSU" == ORIGINAL_P479_KSU_FULL
    return after.encode()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", type=Path, required=True)
    ap.add_argument("--mode", choices=("stage", "verify"), required=True)
    ap.add_argument("--report", type=Path)
    args = ap.parse_args()
    kbuild = args.root / "KernelSU/kernel/Kbuild"
    backup = args.root / "ci/P479-original-KernelSU.Kbuild"
    assert kbuild.is_file() and kbuild.stat().st_size > 0
    if args.mode == "stage":
        assert not backup.exists(), "refusing overwrite of original KernelSU source evidence"
        original = kbuild.read_bytes()
        new = derive(original)
        backup.parent.mkdir(parents=True, exist_ok=True)
        backup.write_bytes(original)
        kbuild.write_bytes(new)
    else:
        assert backup.is_file(), "original KernelSU Kbuild must be preserved in ci"
        original = backup.read_bytes()
        new = derive(original)
        assert kbuild.read_bytes() == new, "direct-source KernelSU Kbuild not exactly the documented adaptation"
    evidence = {
        "schema": "p479-kernelsu-direct-source-v1",
        "original_kbuild_sha256": digest(original),
        "direct_source_kbuild_sha256": digest(new),
        "original_ksu_git_head": "239e1e8871b8fcd51a6e5b3002e0ba522fdd99fb",
        "original_ksu_revision_count": 4471,
        "original_p479_ksu_version_code": ORIGINAL_P479_KSU_VERSION,
        "original_p479_ksu_version_full": ORIGINAL_P479_KSU_FULL,
        "original_submodule_git_requirement_removed": True,
        "direct_source_version_is_historical_p479": True,
        "binary_equivalence_required": True,
        "flash_authorized": False,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(evidence, indent=2, sort_keys=True) + "\n")
    print("P479 KernelSU direct-source Kbuild fidelity PASS; exact original version preserved, no nested git, NO FLASH")


if __name__ == "__main__":
    main()
