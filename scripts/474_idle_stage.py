#!/usr/bin/env python3
"""P474: log the actual forced-idle-poll state from pinned 5.10 idle.c."""
import argparse
import json
from pathlib import Path

MARK = "P474 CMDLINE nohlt=%d cpu_idle_force_poll=%d"
ANCHOR = '__setup("hlt", cpu_idle_nopoll_setup);\n#endif'
PATCH = r'''
/*
 * P474: report the actual idle poll state after boot argument parsing.
 * No behavioural change: the same Image is used for NORMAL and HLT boots.
 */
static int __init p474_cmdline_idle_report(void)
{
	int force_poll = READ_ONCE(cpu_idle_force_poll);

	pr_info("P474 CMDLINE nohlt=%d cpu_idle_force_poll=%d\n",
		force_poll != 0, force_poll);
	return 0;
}
late_initcall(p474_cmdline_idle_report);
'''

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", required=True, type=Path)
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--report", type=Path)
    args = parser.parse_args()
    p = args.root / "kernel/sched/idle.c"
    src = p.read_text()
    if not args.check_only:
        if src.count(ANCHOR) != 1 or "p474_cmdline_idle_report" in src:
            raise SystemExit("P474 pinned idle.c anchor mismatch or already staged")
        src = src.replace(ANCHOR, ANCHOR + "\n" + PATCH, 1)
        p.write_text(src)
    for expected in (MARK, "READ_ONCE(cpu_idle_force_poll)",
                     "late_initcall(p474_cmdline_idle_report)",
                     '__setup("nohlt", cpu_idle_poll_setup)',
                     '__setup("hlt", cpu_idle_nopoll_setup)'):
        if expected not in src:
            raise SystemExit("P474 source check missing: " + expected)
    if src.count(MARK) != 1:
        raise SystemExit("P474 diagnostic marker must be unique")
    report = {
        "phase": "P474-CPU-IDLE-NOHLT-A-B",
        "status": "SOURCE_PASS",
        "kernel_source": str(p),
        "state": "actual cpu_idle_force_poll, sampled at late_initcall",
        "behavior_change": False,
        "no_arm": True,
    }
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(json.dumps(report, sort_keys=True, indent=2) + "\n")
    print("P474 kernel idle state marker staged PASS, no behavior change")

if __name__ == "__main__":
    main()
