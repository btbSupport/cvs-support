"""Rules that pick a cost row by a text they build, checked against real carts.

Some OneCPQ actions fill a cost dropdown with a text instead of an option, e.g. VCDR
`bushCostLookup = CONCAT(SELECTEDVALUE(axleBearing), ' ', SELECTEDVALUE(axleType), ' Bush')`.
The configurator then selects the option whose text (the cost row's boq_identifier) equals that
text; when none does, the lookup stays empty, the cost is 0 and the BOQ line is missing. The
formula engine runs in the browser, so nothing on the server notices.

lost_texts() re-runs those actions on the carts of the last months with the option texts as they
are now. A text is reported when it matches no option although most carts that build it had a
row selected when they were configured, and the rule no longer builds that row's key on any cart:
the row's key no longer equals what the rule builds. Carts store the option id, so old carts and
quotes are not affected; new configurations are. Stale lookups are not reported: when a text matches
nothing the configurator keeps the earlier row, so texts that rarely had a row ('GI 0' when no angle
is used) or whose row the rule still reaches with other choices are left out.
"""

import re
from collections import Counter, defaultdict

import frappe

COST = "FTOCountryWiseCost"
MIN_CARTS = 3
MIN_SHARE = 0.5

_TOKENS = re.compile(r"\s*(?:(?P<str>'[^']*')|(?P<num>\d+(?:\.\d+)?)|(?P<id>[A-Za-z_][A-Za-z0-9_]*)"
	r"|(?P<op>==|!=|>=|<=|\|\||&&|[(),<>+\-*/!]))")
_OPTION_TOKEN = re.compile(r"^\$\[([^\]]*)\]$")


class Unknown(Exception):
	"""The expression uses something this evaluator does not know; the cart is skipped."""


def parse(text):
	toks, pos = [], 0
	while pos < len(text):
		m = _TOKENS.match(text, pos)
		if(not m):
			if(text[pos:].strip()): raise Unknown(f"cannot read {text[pos:pos + 20]!r}")
			break
		pos = m.end()
		toks.append((m.lastgroup, m.group(m.lastgroup)))
	i = 0

	def peek():
		return toks[i] if i < len(toks) else (None, None)

	def expr():
		nonlocal i
		node = atom()
		while peek()[0] == "op" and peek()[1] not in ("(", ")", ","):
			op = toks[i][1]
			i += 1
			node = ("op", op, node, atom())
		return node

	def atom():
		nonlocal i
		kind, val = peek()
		i += 1
		if(kind == "str"): return ("str", val[1:-1])
		if(kind == "num"): return ("num", float(val))
		if(kind == "op" and val == "("):
			node = expr()
			i += 1
			return node
		if(kind == "op" and val in ("!", "-")): return ("op", val, None, atom())
		if(kind == "id"):
			if(peek()[1] != "("): return ("id", val)
			i += 1
			args = []
			while peek()[1] not in (")", None):
				args.append(expr())
				if(peek()[1] == ","): i += 1
			i += 1
			return ("call", val.upper(), args)
		raise Unknown(f"unexpected {val!r}")

	return expr()


def _num(v):
	try:
		return float(v)
	except (TypeError, ValueError):
		return 0.0


def _fmt(v):
	if(isinstance(v, float)): return str(int(v)) if v == int(v) else str(v)
	return "" if v is None else str(v)


class Options:
	"""Option id -> text as the configurator shows it now (value, or the object's data_text_field)."""

	def __init__(self):
		self.fts = {r.name: r for r in frappe.get_all("BtbFeatureType", fields=["name", "object_type", "data_text_field"])}
		self.items = {r.name: r for r in frappe.get_all("BtbFeatureTypeItem",
			fields=["name", "feature_type", "object", "value"], limit_page_length=0)}
		self.by_ft = defaultdict(list)
		for it in self.items.values():
			self.by_ft[it.feature_type].append(it.name)
		self._objects = {}

	def obj(self, doctype, name):
		if(doctype not in self._objects):
			self._objects[doctype] = {r.name: r for r in frappe.get_all(doctype, fields=["*"], limit_page_length=0)}
		return self._objects[doctype].get(name)

	def text(self, option, attr=None):
		it = self.items.get(option)
		if(not it): return None
		ft = self.fts.get(it.feature_type)
		if(ft and ft.object_type):
			o = self.obj(ft.object_type, it.object)
			return None if o is None else _fmt(o.get(attr or ft.data_text_field or "name"))
		return _fmt(it.value)


def evaluate(node, env, opts):
	"""Value of a rule expression for one cart; env = feature field -> stored value (option id or number)."""
	kind = node[0]
	if(kind == "str"): return node[1]
	if(kind == "num"): return node[1]
	if(kind == "id"): raise Unknown(node[1])
	if(kind == "op"):
		op = node[1]
		if(op == "!"): return not evaluate(node[3], env, opts)
		if(op == "-" and node[2] is None): return -_num(evaluate(node[3], env, opts))
		a, b = evaluate(node[2], env, opts), evaluate(node[3], env, opts)
		if(op == "=="): return _fmt(a) == _fmt(b)
		if(op == "!="): return _fmt(a) != _fmt(b)
		if(op == "||"): return bool(a) or bool(b)
		if(op == "&&"): return bool(a) and bool(b)
		if(op in (">", "<", ">=", "<=")):
			x, y = _num(a), _num(b)
			return {">": x > y, "<": x < y, ">=": x >= y, "<=": x <= y}[op]
		if(op == "+"): return _num(a) + _num(b)
		if(op == "*"): return _num(a) * _num(b)
		raise Unknown(op)
	fn, args = node[1], node[2]

	def stored(i):
		if(args[i][0] != "id"): raise Unknown(fn)
		return env.get(args[i][1])

	if(fn == "CONCAT"): return "".join(_fmt(evaluate(a, env, opts)) for a in args)
	if(fn == "IIF"): return evaluate(args[1] if evaluate(args[0], env, opts) else args[2], env, opts)
	if(fn == "NOT"): return not evaluate(args[0], env, opts)
	if(fn in ("SELECTEDVALUE", "TEXT")):
		v = stored(0)
		if(v in (None, "")): return ""
		t = opts.text(v)
		if(t is not None): return t
		return _fmt(_num(v)) if re.fullmatch(r"-?\d+(\.\d+)?", str(v)) else str(v)
	if(fn == "NUMBER"): return _num(stored(0))
	if(fn == "COUNT"): return 0.0 if stored(0) in (None, "", "0") else 1.0
	if(fn == "CONTAINS"):
		v = stored(0)
		if(not v): return False
		for a in args[1:]:
			want = _fmt(evaluate(a, env, opts))
			m = _OPTION_TOKEN.match(want)
			if(m and m.group(1) in (v, opts.text(v))): return True
			if(want == opts.text(v)): return True
		return False
	if(fn == "OBJECTATTRIBUTEF"):
		v = stored(0)
		return (opts.text(v, attr=_fmt(evaluate(args[1], env, opts))) or "") if v else ""
	raise Unknown(fn)


def text_lookup_actions(opts):
	"""Active actions that fill a dropdown over cost rows with a built text (not a plain option token)."""
	features = defaultdict(list)
	for r in frappe.db.sql("""select s.bundle, f.name, f.field, l.feature_type from `tabBtbFeature` f
			join `tabBtbStructure` s on s.name = f.structure left join `tabBtbFeatureLink` l on l.parent = f.name""",
			as_dict=True):
		features[(r.bundle, r.field)].append(r)
	out = []
	for a in frappe.db.sql("""select a.name, a.impact_fields, a.formula, a.constraint, ic.bundle
			from `tabBtbImplementationConstraintAction` a
			join `tabBtbImplementationConstraint` ic on ic.name = a.implementation_constraint
			where a.type = 'Include Value' and ifnull(a.active, 1) = 1 and ifnull(ic.active, 1) = 1""", as_dict=True):
		text = (a.formula or a.constraint or "").strip()
		if(not text or _OPTION_TOKEN.match(text.strip("'"))): continue
		for field in [f.strip() for f in (a.impact_fields or "").split(",") if f.strip()]:
			targets = [f for f in features.get((a.bundle, field), [])
				if opts.fts.get(f.feature_type) and opts.fts[f.feature_type].object_type == COST]
			if(not targets): continue
			try:
				tree = parse(text)
			except Unknown:
				continue
			inputs = set(re.findall(r"\(\s*([A-Za-z_][A-Za-z0-9_]*)", text)) | {field}
			out.append(frappe._dict(action=a.name, bundle=a.bundle, field=field, tree=tree,
				feature_ids={f.name: f.field for i in inputs for f in features.get((a.bundle, i), [])},
				target_fts={f.feature_type for f in targets}))
	return out


def lost_texts(months=12):
	"""[(action, bundle, field, text, carts building it, carts that had a row, most used row, its key now)]"""
	opts = Options()
	actions = text_lookup_actions(opts)
	if(not actions): return []
	feature_ids = {fid for a in actions for fid in a.feature_ids}
	since = frappe.utils.add_months(frappe.utils.nowdate(), -months)
	carts = defaultdict(dict)
	for parent, feature, value in frappe.db.sql("""select cf.parent, cf.feature, cf.value from `tabBtbCartItemFeature` cf
			join `tabBtbCartItem` ci on ci.name = cf.parent
			where ci.creation >= %s and cf.feature in %s""", (since, list(feature_ids))):
		carts[parent][feature] = value

	problems = []
	for a in actions:
		shown = {opts.text(o) for ft in a.target_fts for o in opts.by_ft[ft]}
		built, had_row, rows, reached = Counter(), Counter(), defaultdict(Counter), set()
		for values in carts.values():
			env = {a.feature_ids[f]: v for f, v in values.items() if f in a.feature_ids}
			if(not env): continue
			try:
				text = _fmt(evaluate(a.tree, env, opts))
			except Unknown:
				continue
			reached.add(text)
			if(not text or text in shown): continue
			built[text] += 1
			chosen = env.get(a.field)
			if(chosen and chosen in opts.items):
				had_row[text] += 1
				rows[text][opts.items[chosen].object] += 1
		for text, n in built.items():
			if(had_row[text] < MIN_CARTS or had_row[text] < MIN_SHARE * n): continue
			row = rows[text].most_common(1)[0][0]
			key = frappe.db.get_value(COST, row, "boq_identifier")
			# a row the rule still reaches on other carts is a stale pick (the lookup kept an earlier
			# row when the text matched nothing), not a lost key
			if(key in reached): continue
			problems.append((a.action, a.bundle, a.field, text, n, had_row[text], row, key))
	return problems
