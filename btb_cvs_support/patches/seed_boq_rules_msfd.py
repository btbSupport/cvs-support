"""Fire & Smoke Dampers (MSFD, BUN5): BOQ from BOQ Rule instead of boq_format.JSON (Phase 2)."""

from btb_cvs_support.patches.seed_boq_rules import seed


def execute():
	seed("MSFD")
