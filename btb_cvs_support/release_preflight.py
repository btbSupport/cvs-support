"""Read-only pre-flight check for the cost cleanup + FRAD + BOQ identifier release (2026-11).

Run on every site after pulling the code and BEFORE `bench migrate`:

    bench --site <site> execute btb_cvs_support.release_preflight.run

Prints GO / WARN / STOP per check and a verdict. STOP means the migrate would stop half-way or
leave the site wrong: fix the cause first. Nothing is written to the database or the bench.
"""

import json
import os
import subprocess
import time

import frappe
from frappe.modules.patch_handler import executed, get_all_patches

COST = "FTOCountryWiseCost"
RELEASE_PATCHES = [
	"btb_cvs_support.patches.ftocvsunique_cleanup",
	"btb_cvs_support.patches.fto_ulrd_actuator_country_cost",
	"btb_cvs_support.patches.fto_ulrd_actuator_cart_codes",
	"btb_cvs_support.patches.fto_cost_item_code_as_text",
	"btb_cvs_support.patches.fto_cost_type_country_specific",
	"btb_cvs_support.patches.fto_cost_fill_blank_item_code",
	"btb_cvs_support.patches.fto_cost_cleanup",
	"btb_cvs_support.patches.fto_cost_final_prices",
	"btb_cvs_support.patches.fix_onecpq_bundle_rule_drift",
	"btb_cvs_support.patches.add_fire_rated_access_doors",
	"btb_cvs_support.patches.fto_boq_identifiers",
	"btb_cvs_support.patches.fix_cart_sleeve_length_inch",
	"btb_cvs_support.patches.seed_boq_rules_ulrd",
	"btb_cvs_support.patches.seed_boq_rules_sil",
	"btb_cvs_support.patches.seed_boq_rules_vcdr",
	"btb_cvs_support.patches.seed_boq_rules_cfd",
	"btb_cvs_support.patches.seed_boq_rules_msfd",
	"btb_cvs_support.patches.seed_boq_rules_vcda",
]
SITE_COUNTRY = {"cvsuae": "UAE", "cvsqatar": "Qatar", "cvsksa": "KSA", "badregypt": "Egypt"}
PLAN_OF_COUNTRY = {"UAE": "cvsuae", "Qatar": "cvsqatar", "KSA": "cvsksa", "Egypt": "badregypt"}
FRAD_ROWS = {f"FTO{i:05d}" for i in range(1, 25)}
BACKUP_MAX_AGE_H = 24


class Report:
	def __init__(self):
		self.lines = []

	def add(self, level, check, msg):
		self.lines.append((level, check, msg))

	def verdict(self):
		levels = {lvl for lvl, _c, _m in self.lines}
		return "STOP" if "STOP" in levels else "GO (read the WARN lines)" if "WARN" in levels else "GO"


def run():
	r = Report()
	country = check_country(r)
	check_code(r)
	state = check_patch_log(r)
	check_pending(r)
	if state == "pending":
		survivors = check_cost_rows(r, country)
		check_identifiers(r)
		check_final_prices(r, country, survivors)
	check_backup(r)
	info(r)

	print(f"\nRelease pre-flight for site {frappe.local.site}\n" + "-" * 78)
	for level, check, msg in r.lines:
		print(f"{level:5} {check:16} {msg}")
	print("-" * 78 + f"\nVERDICT: {r.verdict()}\n")
	return r.verdict()


# ------------------------------------------------------------------ checks


def check_country(r):
	site = frappe.local.site or ""
	country = frappe.conf.get("cvs_country")
	if country:
		if country in PLAN_OF_COUNTRY:
			r.add("GO", "country", f"site_config cvs_country = {country}")
			return country
		r.add("STOP", "country", f"site_config cvs_country = {country!r}; must be one of {', '.join(PLAN_OF_COUNTRY)}")
		return None
	country = next((c for p, c in SITE_COUNTRY.items() if site.startswith(p)), None)
	if country:
		r.add("GO", "country", f"{country} from the site name (no cvs_country in site_config)")
	else:
		r.add("STOP", "country", f"cannot tell the country of {site!r}: set \"cvs_country\" (UAE, Qatar, KSA or Egypt) "
			"in its site_config.json")
	return country


def check_code(r):
	for app in ("btb_cvs_support", "onecpq_connect"):
		path = os.path.dirname(frappe.get_app_path(app))
		head = git(path, "log", "-1", "--format=%h %s")
		branch = git(path, "rev-parse", "--abbrev-ref", "HEAD")
		r.add("INFO", "code", f"{app}: {branch} {head}")
		changed = [l for l in (git(path, "status", "--porcelain") or "").splitlines() if l.strip()]
		fixtures = [l for l in changed if "/fixtures/" in l]
		if fixtures:
			r.add("STOP", "code", f"{app}: {len(fixtures)} uncommitted fixture files - discard them "
				"(git checkout -- btb_cvs_support/fixtures) and pull again")
		other = [l for l in changed if l not in fixtures and "/public/dist/" not in l]
		if other:
			r.add("WARN", "code", f"{app}: {len(other)} other uncommitted changes, e.g. {other[0].strip()}")
	if not frappe.db.exists("DocField", {"parent": "BtbImplementationConstraintAction", "fieldname": "type",
			"options": ["like", "%Lock Field%"]}):
		r.add("INFO", "code", "onecpq_connect 'Lock Field' action type not in the database yet (comes with the migrate)")


def check_patch_log(r):
	done = [p for p in RELEASE_PATCHES if executed(p)]
	if not done:
		r.add("GO", "patch log", f"none of the {len(RELEASE_PATCHES)} release patches has run")
		return "pending"
	if len(done) == len(RELEASE_PATCHES):
		r.add("INFO", "patch log", "all release patches have run already: this site is released")
		return "released"
	r.add("STOP", "patch log", "only some release patches are marked as run: " + ", ".join(p.split(".")[-1] for p in done)
		+ ". A patch marked as run without its data (e.g. fto_cost_cleanup with 'no plan') is skipped by the "
		"migrate; check those first (bench run-patch --force after fixing the cause)")
	return "partial"


def check_pending(r):
	pending = [p for p in get_all_patches() if not executed(p)]
	extra = [p for p in pending if p not in RELEASE_PATCHES]
	r.add("INFO", "pending", f"{len(pending)} patches will run on migrate")
	if extra:
		r.add("WARN", "pending", f"{len(extra)} patches outside this release will run too: " + ", ".join(extra[:8])
			+ (" ..." if len(extra) > 8 else ""))


def check_cost_rows(r, country):
	"""Rows after the planned merges must be exactly the rows the BOQ identifier patch expects."""
	if not country:
		return set()
	path = frappe.get_app_path("btb_cvs_support", "patches", "fto_cost_cleanup_plans", f"{PLAN_OF_COUNTRY[country]}.json")
	with open(path) as f:
		plan = json.load(f)
	rows = {x.name: x for x in frappe.get_all(COST, fields=["name", "product_name"])}
	named = {u["row"] for u in plan["updates"]} | set(plan["fill_country"])
	members = set()
	for m in plan["merges"]:
		named |= {m["survivor"], *m["members"]}
		members |= set(m["members"]) - {m["survivor"]}
	missing = sorted(named - set(rows))
	if missing:
		r.add("STOP", "cost rows", f"{len(missing)} rows of the cleanup plan are missing: {', '.join(missing[:10])}")
	else:
		r.add("GO", "cost rows", f"{len(rows)} rows; all {len(named)} rows of the cleanup plan exist")

	expect = {}
	for u in plan["updates"]:
		if u.get("expect_name"): expect[u["row"]] = u["expect_name"]
	for m in plan["merges"]:
		expect.update(m.get("expect") or {})
	differ = [n for n, name in expect.items() if n in rows and (rows[n].product_name or "").strip() != name.strip()]
	if differ:
		r.add("WARN", "cost rows", f"{len(differ)} rows have another product name than the plan expects "
			f"(the cleanup logs and skips them), e.g. {differ[0]}: {rows[differ[0]].product_name!r} vs {expect[differ[0]]!r}")

	survivors = set(rows) - members
	with open(frappe.get_app_path("btb_cvs_support", "patches", "fto_boq_identifiers.json")) as f:
		wanted = set(json.load(f)["identifiers"]) - FRAD_ROWS
	extra, lacking = sorted(survivors - wanted - FRAD_ROWS), sorted(wanted - survivors)
	if extra or lacking:
		r.add("STOP", "cost rows", f"after the cleanup this site would hold other rows than the BOQ identifier list "
			f"(the migrate stops there). Extra: {', '.join(extra[:10]) or '-'}. Missing: {', '.join(lacking[:10]) or '-'}")
	else:
		r.add("GO", "cost rows", f"after the cleanup: {len(wanted)} rows + 24 FRAD rows = the BOQ identifier list")
	return survivors


def check_identifiers(r):
	with open(frappe.get_app_path("btb_cvs_support", "patches", "fto_boq_identifiers.json")) as f:
		ids = json.load(f)["identifiers"]
	have = frappe.get_all(COST, filters={"boq_identifier": ["is", "set"]}, fields=["name", "boq_identifier"])
	differ = [f"{x.name}: {x.boq_identifier!r} (expected {ids[x.name]!r})" for x in have
		if x.name in ids and x.boq_identifier.strip() != ids[x.name]]
	if differ:
		r.add("STOP", "identifiers", f"{len(differ)} rows already carry another BOQ identifier: " + "; ".join(differ[:5]))
	else:
		r.add("GO", "identifiers", f"{len(have)} rows already have an identifier, all as expected")


def check_final_prices(r, country, survivors):
	if not country:
		return
	with open(frappe.get_app_path("btb_cvs_support", "patches", "fto_cost_final_prices.json")) as f:
		rows = set(json.load(f)["costs"].get(country, {}))
	lost = sorted(rows - survivors)
	if lost:
		r.add("STOP", "final prices", f"rows with a final cost would not exist after the cleanup: {', '.join(lost)}")
	else:
		r.add("GO", "final prices", f"{len(rows)} final costs for {country}, all rows survive the cleanup")


def check_backup(r):
	folder = frappe.get_site_path("private", "backups")
	files = [os.path.join(folder, f) for f in os.listdir(folder)] if os.path.isdir(folder) else []
	dbs = [f for f in files if f.endswith((".sql.gz", ".sql"))]
	if not dbs:
		r.add("STOP", "backup", f"no database backup in {folder}: run bench --site {frappe.local.site} backup")
		return
	newest = max(dbs, key=os.path.getmtime)
	age = (time.time() - os.path.getmtime(newest)) / 3600
	if age > BACKUP_MAX_AGE_H:
		r.add("STOP", "backup", f"newest backup is {age:.0f} h old ({os.path.basename(newest)}): take a fresh one")
	else:
		r.add("GO", "backup", f"{os.path.basename(newest)} ({age:.1f} h old)")


def info(r):
	frad = frappe.get_all(COST, filters={"name": ["in", list(FRAD_ROWS)]}, pluck="name")
	r.add("INFO", "FRAD", f"{len(frad)}/24 FRAD cost rows exist already; BUN11 "
		+ ("exists" if frappe.db.exists("BtbBundle", "BUN11") else "does not exist yet"))
	r.add("INFO", "FTOCVSUnique", f"{frappe.db.count('FTOCVSUnique')} rows (the cleanup removes the unused ones)")
	if frappe.db.table_exists("BOQ Rule"):
		r.add("INFO", "BOQ rules", f"{frappe.db.count('BOQ Rule', {'product_family': 'AD'})} AD BOQ rules")


def git(path, *args):
	try:
		return subprocess.run(["git", "-C", path, *args], capture_output=True, text=True, timeout=30).stdout.strip()
	except Exception as e:  # noqa: BLE001
		return f"(git failed: {e})"
