"""FRAD: models RAPI and RAPB no longer offer a 5.0 mm frame (customer feedback, 2026-11-26).

Frame thickness 5.0 stays for RAPW only. The mapping constraint "model & material -> frame thickness" (47u2001njb)
had 5.0 for RAPI and RAPB in GI, SS304L and SS316L; those 6 entries are removed. bundle_specs records.json and
spec.json no longer contain them, so a site that runs add_fire_rated_access_doors after this change never gets
them; this patch removes them where FRAD was added before.

An entry is removed only if it still maps the same model/material to 5.0; anything else is left and reported.
Existing carts are not changed: carts already configured as RAPI/RAPB with a 5.0 frame are listed in the log.
Safe to run again.
"""

import frappe

# entry name: (model & material option, frame thickness option)
ENTRIES = {
	"47uu137ek9": ("FTI00076", "FTI00020"),  # RAPI GI     -> 5.0
	"47vi66brdu": ("FTI00078", "FTI00020"),  # RAPI SS304L -> 5.0
	"47vrrlolr4": ("FTI00079", "FTI00020"),  # RAPI SS316L -> 5.0
	"47v36j925l": ("FTI00080", "FTI00020"),  # RAPB GI     -> 5.0
	"47vtdonr98": ("FTI00082", "FTI00020"),  # RAPB SS304L -> 5.0
	"47v2a2co57": ("FTI00083", "FTI00020"),  # RAPB SS316L -> 5.0
}
CONSTRAINT = "47u2001njb"
MODEL, FRAME, MODELS_NO_5MM, FRAME_5MM = "FTR00001", "FTR00004", ("FTI00004", "FTI00005"), "FTI00020"


def log(msg):
	print(f"[frad_no_5mm_frame_rapi_rapb] {msg}")


def execute():
	if not frappe.db.exists("BtbMappingConstraint", CONSTRAINT):
		log("FRAD is not on this site yet: nothing to do")
		return

	removed, other = [], []
	for name, (left, right) in ENTRIES.items():
		row = frappe.db.get_value("BtbMappingConstraintEntry", name, ["mapping_constraint", "left", "right"], as_dict=True)
		if not row:
			continue
		if (row.mapping_constraint, row.left, row.right) != (CONSTRAINT, left, right):
			other.append(f"{name} ({row.left} -> {row.right})")
			continue
		frappe.delete_doc("BtbMappingConstraintEntry", name, ignore_permissions=True, force=True)
		removed.append(name)
	log(f"{len(removed)} RAPI/RAPB 5.0 mm frame entries removed" if removed else "no RAPI/RAPB 5.0 mm frame entry left: nothing to remove")
	if other:
		log(f"left as they are, they no longer map as expected: {', '.join(other)}")

	carts = frappe.db.sql("""
		select distinct m.parent from `tabBtbCartItemFeature` m
		join `tabBtbCartItemFeature` f on f.parent = m.parent and f.feature = %(frame)s and f.value = %(five)s
		where m.feature = %(model)s and m.value in %(models)s""",
		{"frame": FRAME, "five": FRAME_5MM, "model": MODEL, "models": MODELS_NO_5MM}, pluck=True)
	if carts:
		log(f"{len(carts)} existing carts are RAPI/RAPB with a 5.0 mm frame (not changed): {', '.join(carts[:20])}")
