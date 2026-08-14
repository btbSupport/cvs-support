# ADR-0001: BOQ generation from an Order Processing Request

- **Date:** 2026-08-07
- **Status:** Accepted — implemented 2026-08-11
- **App:** btb_cvs_support
- **Customer:** CVS

> **Correction, 2026-08-11.** The premise given for **D7** below was wrong. The
> BOQ file path is *not* deterministic: Frappe appends the tail of the content
> hash when the requested name is already taken, so every generation has been
> producing a genuinely distinct PDF, and the accumulated attachments are real
> superseded documents rather than duplicate rows pointing at one file. D7 has
> been implemented as decided, but it now **discards prior BOQs** rather than
> tidying up redundant rows. See [Why D7](#why-d7-and-why-it-also-changes-the-quotation) —
> this is worth putting back to the stakeholder before release.

## Context

### The flow today

1. A user creates a **Quotation**. It carries a checkbox `custom_customizable`,
   labelled **"Configurator"** on screen.
   - **Ticked** — the quote's line items are generated from **cart items**
     (`BtbCartItem`) configured in the OneCPQ cart. Each `Quotation Item` row
     stores the originating cart item in `custom_cart_item`.
   - **Unticked** — the user keys `Quotation Item` rows in directly. No cart
     item and no configuration data exists.
2. A **Sales Order** is created from the Quotation.
3. One or more **Order Processing Requests** (OPR) are created from the Sales
   Order. An OPR represents a *release* of part of the order — one Sales Order
   in the live data has **477** OPRs against it.

### How the Quotation BOQ works

The BOQ is not derived from the quote line items. It is derived from the
**configuration answers** held on the cart items behind them:

1. The `Output Documents → BOQ` button is added only when
   `custom_customizable == 1`
   ([client_script.json — `Quotation_controller`](../../btb_cvs_support/fixtures/client_script.json)).
2. It calls
   [`boq.provide(quote_name)`](../../btb_cvs_support/api/boq.py), which loads
   every `BtbCartItem` linked to the quote via `BtbCartItemLink`, together with
   every configuration feature answer (material type, casing thickness, casing
   weight, dimensions, …).
3. Those answers are evaluated against the rule book
   [`boq_format.JSON`](../../btb_cvs_support/api/boq_format.JSON) — one entry per
   product family (SIL, VCD, FSD, …), each holding filter conditions and an
   aggregate formula, e.g. *"if material = GI and casing thickness = 0.6, then
   `GI Casing 0.6` (Kg) = `casingWeight` × `cartQty`"*. Evaluation is done by
   [`btb_constraint.exec_formula`](../../btb_cvs_support/api/btb_constraint.py).
4. Results are grouped by product sub-category and rendered into
   [`boq.docx`](../../btb_cvs_support/document/templates/boq.docx) by the external
   OneDoc service, then attached to the Quotation as a private PDF
   ([generator.py](../../btb_cvs_support/document/generator.py)).

Two consequences follow directly and constrain everything below:

- **A BOQ is only possible where configuration answers exist**, i.e. where cart
  items exist, i.e. only for Configurator-ticked quotations. A
  non-Configurator quote has nothing for the formulas to read. This is a
  property of the design, not a gap that can be coded around.
- **Every formula's quantity term is `cartQty`** — the cart item quantity.

### The requirement

The customer wants the same BOQ available at OPR level.

### The gap

An OPR holds no reference to a Quotation or to a cart item. Its two line tables
reach only as far as the Sales Order:

- `Quantities Table` (fieldname `quantities_required`) — `so_detail` → `Sales Order Item`
- `Accessories` (fieldname `accessories`) — `so_detail` → `Sales Order Item`

The trail back to the configuration data is therefore:

```
OPR row → so_detail → Sales Order Item
                          ↓ quotation_item          (set by ERPNext's make_sales_order)
                      Quotation Item
                          ↓ custom_cart_item
                      BtbCartItem → feature answers → existing BOQ engine
```

Every hop is an existing field. `Sales Order Item.quotation_item` and
`prevdoc_docname` are populated by ERPNext's standard mapper
([quotation.py:452](../../../erpnext/erpnext/selling/doctype/quotation/quotation.py#L452))
when the Sales Order is made with the **Quotation → Create → Sales Order**
button. `Sales Order.quotation_reference` is a header-level Custom Field
(Link → Quotation) that some users set by hand.

### Findings from the `cvsuae.localhost` database

These shaped the decisions below and are recorded so the assumptions are
auditable:

| Finding | Figure |
|---|---|
| Sales Order Items with `quotation_item` / `prevdoc_docname` filled | **0 of 122** |
| Sales Orders with `quotation_reference` filled | **2 of 32** |
| `Quantities Table` rows with no `so_detail` (2025) | **1,889 of 2,207** |
| `Quantities Table` rows with no `so_detail` (2026) | **28 of 72** |
| Items with `custom_manufactured_item` ticked | **20 of 3,270** |
| Configurator item codes with that flag ticked | **1** (`FSD-3V-212`) |
| Max OPRs against a single Sales Order | **477** (SO-01374) |

The dev site's Sales Orders were hand-keyed with generic item codes
(`99-VCD`, `99-MISC`), so the item-level link cannot be exercised there.
**Stakeholder confirmed the production process is mixed** — some users press the
standard button, others key the Sales Order in by hand.

### How the two OPR line tables are separated

Both are filled by the OPR's **Get Items from Sales Order** action. The server
returns every pending Sales Order line
([opr.py:63-77](../../btb_cvs_support/api/opr.py#L63-L77)) and the client script
routes each on a single test:

```js
if (items[i].custom_manufactured_item) addQuantity(frm, items[i]);   // Quantities Required
else                                    addAccessory(frm, items[i]); // Accessories
```

`custom_manufactured_item` is a checkbox on the **Item** master.
`Quantities Required` additionally carries duct geometry (Straight/Fittings
sqm and nos, Total sqm) and is the **only** table that feeds the OPR's
production and delivery totals
([opr.py:277-286](../../btb_cvs_support/api/opr.py#L277-L286)); `Accessories` is a
bought-out list that contributes to Approx Value only.

## Decision

Add a **BOQ** action to the Order Processing Request that reuses the existing
BOQ engine and rule book unchanged, driving it from the cart items reached
through each OPR line, at that line's own quantity.

Decisions confirmed with the stakeholder on 2026-08-07:

| # | Decision |
|---|---|
| D1 | The BOQ is computed on **this OPR's row quantities**, not the full Sales Order quantity. |
| D2 | Rows that cannot be traced to a cart item are **skipped**; a partial BOQ is produced and an on-screen warning names the skipped rows. |
| D3 | Document header shows **Customer / OPR # / SO # / Project / Date**, via a new `boq_opr.docx`. |
| D4 | **No role gate** — anyone who can open the OPR can generate it, matching the Quotation BOQ today. |
| D5 | **Both** `Quantities Required` and `Accessories` are read. The Manufactured-Item split is irrelevant to a BOQ. |
| D6 | Tracing uses the item-level link first, then a **strict** header-level fallback that never guesses (see Architecture §2). |
| D7 | Re-generating **replaces** the previous BOQ — the earlier `BOQ_<name>.pdf` attachment is deleted first. Applies to **both** the OPR BOQ and the existing **Quotation** BOQ. |
| D8 | **No workflow-state gate** — the button is available at every state, as on the Quotation. |

### Why D7, and why it also changes the Quotation

Today [`boq.provide`](../../btb_cvs_support/api/boq.py) creates a fresh `File`
row on every click, so repeated generations accumulate near-identically-named
`BOQ_<name>.pdf` attachments and the reader must go by upload time to find the
current one.

**The original rationale here was wrong and is corrected.** It claimed the file
path was deterministic, so every render overwrote the same bytes and the older
`File` rows already pointed at the newest content — "several rows, one
document, no history". The database says otherwise.
[`generator.generate`](../../btb_cvs_support/document/generator.py) does write
to a fixed `/private/files/BOQ_<name>.pdf`, but saving the `File` row makes
Frappe move it aside under `BOQ_<name><hash>.pdf`, where `<hash>` is the tail
of the content MD5. `QTN-25-0341` carries seven such files on disk at four
distinct sizes and seven distinct checksums. Every one is a real, different
BOQ.

So the accumulation is not noise — it is history, and D7 destroys it. The
decision still holds on its merits: a BOQ is a working material list,
re-generated as quantities are adjusted, and a stale-looking attachment on the
record is a real risk of the wrong material being drawn.
**Stakeholder decision, 2026-08-07: the replace behaviour applies to the
Quotation BOQ as well, not just the new OPR one.** The two screens stay
consistent and both end up with exactly one current BOQ. But that decision was
taken on the understanding that nothing was being thrown away, which was not
true, so it should be re-confirmed. If retention is wanted, the cheapest change
is to stop calling `delete_existing_attachment` and instead put a timestamp in
the file name so the current sheet is obvious.

Implemented as a small shared helper called by both entry points, rather than
inside [`generator.generate`](../../btb_cvs_support/document/generator.py) —
putting it in the generator would silently change the Quotation Format and
Production Sheet outputs too, which is not what was asked for. Because the
stored name carries that hash, the helper matches on the stem plus an optional
hex tail rather than on the exact file name.

### Why D8 needs no state gate

The generator already stamps a `DRAFT` watermark on any document whose source is
not submitted (`docstatus != 1`), so a pre-approval sheet is self-identifying.
Gating the button would block the planning use — stores looking ahead at what a
release will consume — and would need maintaining as the 15-state OPR workflow
evolves. The button is therefore offered at every state, including `Cancelled`;
the watermark and the OPR's own status carry the context.

### Why D5

The routing flag is barely populated and, critically, is **not** set on the item
codes the configurator sells: of `SKU36` (3,999 configurator lines),
`CDF-165-AF-M`, `SSD-R`, `FD-R`, `FSD-3V-211`, `CDW-165-AF-M` and the rest, only
`FSD-3V-212` is flagged. Filtering the BOQ to `Quantities Required` would
silently drop most configured products. Reading both tables costs nothing —
genuine accessories (sealant, tape, gaskets) have no configuration and simply
fail the trace, landing in the D2 warning.

**No core/ERPNext changes. No changes to other custom apps. No schema change.**
Everything lives under `apps/btb_cvs_support/`.

## Scope

### In scope

As built:

- New server module [`api/opr_boq.py`](../../btb_cvs_support/api/opr_boq.py) —
  the whitelisted `provide(opr_name)`, the resolver (`resolve_rows`,
  `cart_items_by_so_detail`, `cart_items_by_item_code`) and the quantity
  substitution (`apply_row_quantities`).
- Additive changes to
  [`btb_quotation.py`](../../btb_cvs_support/api/btb_quotation.py):
  `get_items_by_cart_items` / `populate_cart_item_model_by_cart_items` beside
  the existing quotation-driven pair, and a `cartItemId` key on the built model
  so a model can be matched back to the OPR row it came from.
- New shared helper `delete_existing_attachment` in
  [`document/generator.py`](../../btb_cvs_support/document/generator.py),
  alongside `generate` rather than inside it.
- New template `document/templates/boq_opr.docx`.
- `Output Documents → BOQ` button plus a `create_boq` handler on the OPR form,
  hand-spliced into the `opr_controller` Client Script fixture **and** into the
  live `tabClient Script` row.
- Defect fix: `subCategoryMap.clear()` at the top of `populate_cart_detail` in
  [`boq.py`](../../btb_cvs_support/api/boq.py) — placed there, not in
  `provide`, because the OPR path enters at `populate_cart_detail`.
- **Change to the existing Quotation BOQ (D7):** `boq.provide` deletes the prior
  `BOQ_<quote>.pdf` attachment before rendering, via that shared helper. Its
  document content and template are untouched.

### Out of scope

- Any change to `boq_format.JSON` or to the formula engine in
  `btb_constraint.py`. The rule book and evaluator are reused verbatim.
- Any change to the Quotation BOQ's **document content, template or the data it
  is built from**. Only its attachment-replacement behaviour changes (D7).
- The **Quotation Format** and **Production Sheet** outputs. They keep their
  current accumulate-on-repeat behaviour; D7 is scoped to the BOQ only. Worth
  raising with the customer separately if the same annoyance applies there.
- BOQ for non-Configurator quotations — impossible by design, no configuration
  data exists.
- Any change to the custom DocTypes `Order Processing Request`,
  `Quantities Table` or `Accessories`.
- **Correcting the `custom_manufactured_item` flag.** See
  [Known defect raised separately](#known-defect-raised-separately).

## Architecture

### 1. Entry point

```python
# btb_cvs_support/api/opr_boq.py
@frappe.whitelist()
def provide(opr_name: str) -> dict
```

Returns `{"status": ..., "skipped": [...]}` so the client can raise the D2
warning. Flow:

1. Resolve OPR rows → `(cart_item_name, quantity)` pairs plus a list of skipped
   rows (§2).
2. If no row resolves, return without generating a document and let the client
   explain why.
3. Build the cart item models (§3), overriding each model's quantity with the
   OPR row quantity.
4. Hand the models to the **existing**
   [`boq.populate_cart_detail(ciModels)`](../../btb_cvs_support/api/boq.py) —
   it already takes a prepared model list, so the engine needs no change.
5. **Delete any existing `BOQ_<opr_name>.pdf`** attached to this OPR (D7), via
   the shared helper `delete_existing_attachment(doctype, name, file_name)` —
   `File` rows scoped by `attached_to_doctype` and `attached_to_name`, then
   matched against `^BOQ_<opr_name>[0-9a-f]*\.pdf$` and removed with
   `frappe.delete_doc(..., force=1)`. The optional hex tail is Frappe's
   content-hash suffix; allowing only hex means a document whose name is a
   prefix of another (`QTN-25-0311` / `QTN-25-0311-1`) cannot sweep up its
   neighbour's sheet. The same helper is called from `boq.provide` for the
   Quotation.

   This is done **before** rendering, not after. Deleting afterwards would risk
   Frappe's `File.on_trash` removing the *newly written* file. Note that this
   genuinely discards the earlier PDF — see the correction under
   [Why D7](#why-d7-and-why-it-also-changes-the-quotation). If the render then
   fails, the user retries and the OPR is left with no BOQ until they do.
6. Render `boq_opr.docx` through the existing
   [`generator.generate`](../../btb_cvs_support/document/generator.py) with
   `doc_type="Order Processing Request"`, `doc_name=opr_name`,
   `file_name=f"BOQ_{opr_name}.pdf"`.

### 2. The resolver — first hit wins, never guesses

For every row in `quantities_required` **and** `accessories` (D5):

**Step 1 — item-level link (authoritative).**

```
row.so_detail
  → `tabSales Order Item`.quotation_item
  → `tabQuotation Item`.custom_cart_item
```

Accept when non-empty and the cart item exists.

**Step 2 — strict header-level fallback.** Only if step 1 yields nothing and
`Sales Order.quotation_reference` names a Quotation: match the row's
`item_code` against that quotation's `Quotation Item` rows.
**Accept only when exactly one line carries that item code, and it is
cart-linked.** Two lines sharing an item code (common — the sample OPR-2602001
carries `99-VCD` twice) are ambiguous and are **not** resolved.

Ambiguity is counted over *all* the quotation's lines, not only the cart-linked
ones. A quotation carrying one configured and one hand-keyed line of the same
item code could be resolved by looking only at the configured side, but that is
still a guess about which line the OPR row came from, and D6 says never guess.

**Step 3 — skip.** Anything else (no `so_detail`, no quotation link, ambiguous
match, quotation line with no `custom_cart_item`) is recorded as skipped with
its table, row index and item code, and reported to the user (D2).

No rate/quantity/positional tie-breaking. A wrong tie-break would put the wrong
configuration into a material list with nothing downstream to catch it; a
skipped row is visible and correctable.

### 3. Quantity substitution (D1)

`boq_format.JSON` formulas multiply per-unit values by the field `cartQty`.
[`populate_cart_models`](../../btb_cvs_support/api/btb_quotation.py) builds that
key from the cart item's own quantity. Two additive changes:

- `populate_cart_models` also emits the cart item id on the model (e.g.
  `cartItemId`), so a model can be matched back to the OPR row it came from.
  Additive — the Quotation BOQ and the Production Sheet ignore the extra key.
- `opr_boq` overwrites each model's `cartQty` (and the display `qty`) with the
  OPR row quantity before evaluation.

UOM is consistent along the chain: the OPR row quantity is copied from the
Sales Order Item, which carries the Quotation Item's UOM, which is the cart
item's model UOM. Partial releases can yield fractional quantities; the
formulas are arithmetic and handle that correctly.

### 4. Document

`boq_opr.docx` is a copy of `boq.docx` with only `word/header2.xml` changed.
That header is a three-row table whose last row is empty, so the extra value
fits without touching the grid:

```
Customer  [[.qt.customer_name]]      OPR #  [[.qt.name]]
Project   [[.qt.project]]            Date   <DATE field>
                                     SO #   [[.qt.sales_order]]
```

Two edits: the `Quote #` label becomes `OPR #`, and the two empty cells in the
third row take the `SO #` label and value. Every other part of the archive —
`word/document.xml` included — is copied byte for byte, so the body (the
sub-category tables of ERP Item Code / Product Description / Unit / Qty, and
the `[[wmtext .qt.water_mark]]` DRAFT watermark) is unchanged by construction.
All four header values live directly on the OPR (`customer_name`, `name`,
`sales_order`, `project`), so no extra lookup is needed. The watermark follows
the same rule as the Quotation BOQ: `DRAFT` unless `docstatus == 1`.

### 5. Client button

In the `opr_controller` Client Script fixture, inside `refresh`, after the
existing `if (old) return;` guard so legacy (pre-2025-03-20) OPRs are excluded.
No `workflow_state` or `docstatus` condition is applied (D8):

```js
frm.add_custom_button(__('BOQ'), function () { create_boq(frm); }, __('Output Documents'));
```

`create_boq` calls `btb_cvs_support.api.opr_boq.provide`, then reports skipped
rows via `frappe.msgprint` and reloads so the attachment appears — the same
pattern as the Quotation's `create_boq`.

The fixture and the live `tabClient Script` row must both be updated (the DB row
is what executes; `bench migrate` syncs the fixture onto it). Per house rule the
fixture is **hand-spliced**, not produced by a blanket `bench export-fixtures`.

### 6. Defect fix — `subCategoryMap`

[`boq.py`](../../btb_cvs_support/api/boq.py) keeps `subCategoryMap` as a
module-level dict that `populate_product_map` writes to and never clears. Two
BOQs generated by the same worker process can therefore leak sub-category →
product-code entries into each other. Adding a second caller makes this more
likely to be hit, so the map is cleared at the start of each run.

## Alternatives considered

**A. Stamp the cart item onto the OPR row at creation time.** Add a `cart_item`
link column to `Quantities Table` and `Accessories`, filled by *Get Items from
Sales Order*, and read it directly. More robust, visible on the form, and
hand-correctable. **Rejected for v1** because those are DB-only custom DocTypes
(`custom = 1`, held in no app's source), the change would need a Custom Field
plus a backfill patch, and it would not help the OPRs that already exist. The
resolver in §2 is the same code either way, so this remains an easy hardening
step if the trace proves unreliable in production.

**B. Looser fallback matching** — break item-code ties on rate, quantity, then
line order. Rejected: traces more rows at the cost of silently attributing the
wrong configuration to a material list.

**C. No fallback at all** — item-level link or nothing. Rejected: with a mixed
Sales Order creation process this would make the feature unavailable for an
unknown share of orders.

**D. Reprint the whole Quotation BOQ against the OPR.** Cheapest, but ignores
partial releases; with 477 OPRs on one Sales Order it would attach the same
full-order document 477 times.

## Consequences

- OPRs whose Sales Order was created with the standard button get a correct,
  release-sized BOQ with no data preparation.
- OPRs on hand-keyed Sales Orders get a BOQ only where the Quotation Reference
  is set and item codes match unambiguously; otherwise the user sees exactly
  which rows were skipped and why.
- Legacy OPRs (pre-2025-03-20) never show the button.
- Exactly one BOQ attachment exists per OPR **and per Quotation** at any time
  (D7). **Superseded sheets are destroyed, not merely de-duplicated** — see the
  correction at the top. If the customer needs an audit trail of what was
  issued to production, that is a separate change (timestamped filenames or a
  version log) and it should be settled before this reaches production.
- Existing Quotations carrying several `BOQ_<quote>.pdf` rows lose all but the
  newest the next time that quotation's BOQ is generated. `QTN-25-0341` has
  seven, `QTN-26-0021` and `QTN-26-0022` two each on the dev site alone.
- The button is present at every workflow state including `Cancelled` (D8);
  anything not yet submitted carries the `DRAFT` watermark.
- Non-Configurator orders never produce a BOQ. This must be communicated to the
  customer as a property of the feature.
- The Quotation BOQ and the Production Sheet gain one unused key on their
  internal model and the `subCategoryMap` fix; no behavioural change.

## Known defect raised separately

`custom_manufactured_item` is ticked on 20 of 3,270 items, and of the
configurator's item codes only `FSD-3V-212` carries it. Configured dampers
therefore land in **Accessories** rather than **Quantities Required**, which
excludes them from the OPR's Total SQM / Total Nos, Produced, Remaining
Production and Remaining Delivery figures
([opr.py:277-286](../../btb_cvs_support/api/opr.py#L277-L286)).

This is a live production-tracking defect, independent of the BOQ. It is
**deliberately not fixed here** (stakeholder decision, 2026-08-07): ticking the
flag would move lines between the two tables and shift sqm/nos totals on orders
that are already being reported on. To be raised with the customer as its own
change.

## Open questions

**Re-confirm D7 with the stakeholder** (raised 2026-08-11). It was agreed on
the understanding that the accumulated attachments were duplicate rows over one
file. They are not — each is a distinct superseded BOQ, and D7 as built deletes
them. The behaviour is implemented as decided; the question is whether the
decision survives the corrected facts.

The two questions raised on 2026-08-07 were resolved into **D7** (replace, not
accumulate) and **D8** (no workflow-state gate).

One assumption remains to be confirmed against production rather than decided:
the share of Sales Orders created with the standard button versus keyed in by
hand. The process is known to be mixed, and the design handles both, but the
proportion determines how often users meet the D2 warning. If hand-keyed orders
dominate, promote **Alternative A** (stamp the cart item at OPR creation) from a
hardening step to the primary mechanism.

The mechanism itself is no longer in doubt: the smoke test of 2026-08-11 showed
the standard button filling `quotation_item` on 20 of 20 lines *and* setting
`quotation_reference`, so a button-created order needs no data preparation at
all. The 0-of-122 figure in the findings table describes this dev site's
hand-keyed history, not a limitation of the trace.

## Verification (post-implementation)

Status as at 2026-08-11, against `cvsuae.localhost`. A full chain was built for
the purpose and left in place:

| Record | What it is |
|---|---|
| `QTN-26-0023` | Configurator quotation, duplicated from `QTN-26-0022` and rebuilt by `amendCPQ` — 20 lines, 20 of its own cart items (`CI750480`–`CI750499`), no overlap with the source. Submitted. |
| `SO-04232` | Created with **Quotation → Create → Sales Order**. Submitted. |
| `OPR-2608001` | Release A — half of every line. 1 `Quantities Required` row, 19 `Accessories`. |
| `OPR-2608002` | Release B — the complementary remainder, 5 rows, plus 4 hand-keyed rows added afterwards to exercise the skip path. |

**The assumption the whole design rests on is confirmed:** the standard mapper
filled `quotation_item` on **20 of 20** Sales Order Items, every one reaching a
live cart item, and it set `Sales Order.quotation_reference` as well — so both
the item-level link and the header fallback were available on the same order.

`custom_manufactured_item` is set on only one of the thirteen item codes
(`CDF-165-3V-M`), so 19 of the 20 OPR rows landed in **Accessories**. Had the
BOQ read only `Quantities Required`, as originally suggested, it would have
covered one line out of twenty. **D5 is what makes the feature work at all.**

| # | Result |
|---|---|
| 1 | **Verified live.** Both OPRs returned `Success` with 0 skipped rows and a real PDF attached. The rendered header reads `Customer Test / OPR # OPR-2608001` over `Project PROJ-0952 / Date 11-Aug-26` over `SO # SO-04232`, and the body table is unchanged. |
| 2 | **Verified live.** Across **all 170** BOQ lines in 5 sub-categories, release A + release B equals the whole-quotation BOQ exactly — zero mismatches beyond rounding. |
| 3 | **Verified live.** Four hand-keyed rows added to `OPR-2608002` were skipped by name while the other five still produced a BOQ: two with no item code, two ambiguous. |
| 4 | **Verified live.** `QTN-26-0023` carries four `CDW-165-AF-M` lines, so the hand-keyed rows for that code were skipped as ambiguous rather than attributed to one of them. |
| 5 | Verified earlier against `OPR-2602001` / `QTN-25-0313`: `Nothing to generate`, four named rows, no attachment touched. |
| 6 | Not run — needs the browser. The button sits after the existing `if (old) return;` guard. |
| 7 | **Verified live.** Generating twice on `OPR-2608001` left exactly one `BOQ_*` attachment, holding the newer content, and the superseded file was removed from disk. |
| 8 | Half verified. The draft OPR's PDF carries the `DRAFT` watermark (seen in the render). The submitted-OPR case was not driven — it needs a transition through the 15-state workflow; `get_opr_details` returns a blank watermark for `docstatus == 1`. |
| 9 | **Verified live.** Three successive generations on `QTN-26-0023` left one attachment each time. See the note below — this needed a site fix first. |
| 10 | Verified for the BOQ: the sub-category grouping and every line value for `QTN-25-0313` are identical before and after an OPR BOQ runs in the same process. Production Sheet not re-run. |
| 11 | Not run. Nothing in the change touches `quotation_format.py` or `production_format.py`. |
| 12 | Verified. Quotation BOQ → OPR BOQ → Quotation BOQ in one process yields identical output for the quotation. |

### Deployment prerequisite found during the smoke test

D7 **throws on any submitted document** unless the site's schema is current.
`File.on_trash` short-circuits for drafts, so the draft OPRs were fine, but on
the submitted Quotation it reaches `ref_doc.meta.protect_attached_files` — a
DocType property that does not exist until `tabDocType` is synced. On
`cvsuae.localhost` this and about twenty other fields across
`Selling Settings`, `Accounts Settings`, `Quotation`, `Sales Order` and
`DocType` were missing, with 38 patches pending; a Quotation could not even be
saved. The smoke test unblocked it with targeted `frappe.reload_doc` calls
(schema only, no patches). **The target site must be migrated before this
feature ships**, or the second BOQ on a submitted document will error.

Separately: `generator.generate` writes to a fixed `/private/files/BOQ_<name>.pdf`
and Frappe then stores a content-hashed copy, leaving the fixed-name file behind
with no `File` row. One orphan per document, overwritten on each render, so it
does not grow — pre-existing, unrelated to this change, but it means the current
BOQ also sits on disk unreferenced.

1. On an OPR whose Sales Order was created with the standard button from a
   Configurator quotation: BOQ generates, header shows OPR # and SO #, and the
   quantities are the OPR's, not the Sales Order's.
2. Two OPRs releasing different portions of the same Sales Order line produce
   proportionally different BOQ quantities that sum to the single-quotation
   BOQ for that line.
3. An OPR with manual rows (no `so_detail`) produces a partial BOQ and names
   those rows in the warning.
4. An OPR whose Sales Order has two lines of the same item code against a
   hand-keyed order: those rows are skipped, not guessed.
5. An OPR tracing to a non-Configurator quotation: no document, clear message.
6. A legacy OPR (created before 2025-03-20): no button.
7. Generating twice on the same OPR leaves **one** `BOQ_<OPR>.pdf` attachment,
   holding the newer content (D7).
8. The button appears on a Draft OPR and the output carries the `DRAFT`
   watermark; it also appears on a submitted OPR without the watermark (D8).
9. Generating twice on the same **Quotation** leaves one `BOQ_<quote>.pdf`
   attachment (D7), and a quotation that already carries several stale rows
   collapses to one on the next generation.
10. Regression — the Quotation BOQ and the Production Sheet produce
    byte-identical *document content* to before the change for the same
    quotation. Only the Quotation BOQ's attachment count changes.
11. Regression — the Quotation Format and Production Sheet still accumulate
    attachments on repeat generation; D7 did not leak into them.
12. Regression — generating a Quotation BOQ and an OPR BOQ back to back in the
    same worker yields correct sub-category grouping in both (the
    `subCategoryMap` fix).
