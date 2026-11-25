"""UL True Round Dampers (ULRD, BUN4): BOQ from BOQ Rule instead of boq_format.JSON (Phase 2 pilot)."""

from btb_cvs_support.patches.seed_boq_rules import seed


def execute():
	seed("ULRD")
