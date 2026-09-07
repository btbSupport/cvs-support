"""BOQ generation from an Order Processing Request (ADR-0001).

An OPR holds no reference to a quotation or to a cart item, so the
configuration answers the BOQ is built from have to be reached line by line:

    OPR row -> so_detail -> `Sales Order Item`.quotation_item
                         -> `Quotation Item`.custom_cart_item
                         -> BtbCartItem -> feature answers -> BOQ engine

The engine and the rule book (boq_format.JSON) are reused unchanged; only the
quantity term is substituted, so the sheet is sized to this release rather than
to the whole Sales Order.
"""

import frappe
from typing import Dict, List, Tuple
from frappe.utils import flt

from .boq import populate_cart_detail
from .btb_quotation import populate_cart_item_model_by_cart_items
from ..document.generator import generate, delete_existing_attachment

TEMPLATE_PATH = "../apps/btb_cvs_support/btb_cvs_support/document/templates/boq_opr.docx"

# (label, OPR fieldname, fieldname holding the item code on that child table).
# Both tables are read - the Manufactured Item split that routes rows between
# them is irrelevant to a BOQ, and is not set on most configurator item codes.
LINE_TABLES = (
    ("Quantities Required", "quantities_required", "item_code"),
    ("Accessories", "accessories", "item"),
)


@frappe.whitelist()
def provide(opr_name: str) -> Dict:
    opr = frappe.get_doc("Order Processing Request", opr_name)
    resolved, skipped = resolve_rows(opr)

    if(not resolved):
        return {"status": "Nothing to generate", "traced": 0, "skipped": skipped}

    ciModels = populate_cart_item_model_by_cart_items(list(resolved.keys()))
    if(ciModels == None):
        return {"status": "Nothing to generate", "traced": 0, "skipped": skipped}

    apply_row_quantities(ciModels, resolved)
    output = {
        "ci": populate_cart_detail(ciModels),
        "qt": get_opr_details(opr)
    }
    file_name = "BOQ_"+opr_name+".pdf"
    # ADR-0001 D7 - an OPR carries one current BOQ, not one per click. Done
    # before rendering: the new File row must not be the one that gets removed.
    delete_existing_attachment("Order Processing Request", opr_name, file_name)
    generate(TEMPLATE_PATH, output, format="pdf", doc_type="Order Processing Request",
             doc_name=opr_name, file_name=file_name, addDigitalSignature=False)
    return {"status": "Success", "traced": len(ciModels), "skipped": skipped}


def resolve_rows(opr) -> Tuple[Dict[str, float], List[Dict]]:
    """Map every OPR line to the cart item behind it.

    Returns ({cart item: quantity}, [skipped row descriptions]). Quantities of
    rows landing on the same cart item are added together.
    """
    rows = []
    for label, fieldname, item_field in LINE_TABLES:
        for row in (opr.get(fieldname) or []):
            rows.append({
                "table": label,
                "idx": row.idx,
                "so_detail": row.get("so_detail"),
                "item_code": row.get(item_field),
                # Accessories.quantity is a Data field, so it arrives as a string
                "quantity": flt(row.get("quantity")),
            })

    by_so_detail = cart_items_by_so_detail([r["so_detail"] for r in rows if r["so_detail"]])
    quotation = header_quotation(opr.sales_order)
    by_item_code, ambiguous = cart_items_by_item_code(quotation)

    resolved: Dict[str, float] = {}
    skipped: List[Dict] = []
    for r in rows:
        cart_item = by_so_detail.get(r["so_detail"]) if r["so_detail"] else None
        if(not cart_item and r["item_code"]): cart_item = by_item_code.get(r["item_code"])
        if(not cart_item):
            skipped.append({
                "table": r["table"],
                "idx": r["idx"],
                "item_code": r["item_code"],
                "reason": skip_reason(r, quotation, ambiguous),
            })
            continue
        resolved[cart_item] = resolved.get(cart_item, 0) + r["quantity"]
    return resolved, skipped


def skip_reason(row, quotation, ambiguous) -> str:
    if(row["item_code"] and row["item_code"] in ambiguous):
        return ("the Quotation Reference " + quotation + " has more than one line for this item code, "
                "so the configuration cannot be identified")
    if(not quotation):
        return ("no configuration could be traced - the Sales Order line does not point back to a "
                "Quotation and the Sales Order has no Quotation Reference")
    if(not row["item_code"]):
        return "the row has no item code to match against " + quotation
    return "no configured line for this item code exists on " + quotation


def cart_items_by_so_detail(so_details: List[str]) -> Dict[str, str]:
    """Step 1 - the item-level link, which is authoritative when it is there.
    Populated by ERPNext's mapper when the Sales Order is made with the
    Quotation -> Create -> Sales Order button."""
    if(not so_details): return {}
    placeholders = ", ".join(["%s"] * len(so_details))
    sql = f"""
        select soi.name so_detail, qi.custom_cart_item cart_item
        from `tabSales Order Item` soi
        join `tabQuotation Item` qi on qi.name = soi.quotation_item
        join `tabBtbCartItem` ci on ci.name = qi.custom_cart_item
        where soi.name in ({placeholders})
    """
    rows = frappe.db.sql(sql, tuple(so_details), as_dict=1)
    return {r.so_detail: r.cart_item for r in rows}


def cart_items_by_item_code(quotation: str) -> Tuple[Dict[str, str], set]:
    """Step 2 - the strict header-level fallback, for Sales Orders that were
    keyed in by hand and only carry a Quotation Reference.

    An item code is accepted only when the quotation carries exactly one line
    for it. Counting every line, not just the configured ones, is deliberate:
    if a code appears twice there is no way to tell which line the OPR row came
    from, and attributing the wrong configuration to a material list is not
    something anything downstream would catch.
    """
    if(not quotation): return {}, set()
    sql = """
        select qi.item_code, qi.custom_cart_item cart_item, ci.name cart_item_exists
        from `tabQuotation Item` qi
        left join `tabBtbCartItem` ci on ci.name = qi.custom_cart_item
        where qi.parent = %s and qi.parenttype = 'Quotation'
    """
    lines: Dict[str, List] = {}
    for r in frappe.db.sql(sql, quotation, as_dict=1):
        lines.setdefault(r.item_code, []).append(r)

    mapping: Dict[str, str] = {}
    ambiguous = set()
    for item_code, matches in lines.items():
        if(len(matches) > 1):
            ambiguous.add(item_code)
            continue
        if(matches[0].cart_item_exists): mapping[item_code] = matches[0].cart_item
    return mapping, ambiguous


def header_quotation(sales_order: str):
    """The hand-keyed fallback route - `Sales Order`.quotation_reference.

    That field is a Custom Field, not a standard one, so it is absent on any
    site that has not had it installed. Ask the meta before the column: an
    unguarded read raises OperationalError 1054, and because this runs before
    the routing in resolve_rows() it would take down BOQ generation for every
    OPR - including the ones that trace fully through so_detail and never need
    the fallback. None is the answer the callers already handle (skip_reason).
    """
    if(not sales_order): return None
    if(not frappe.get_meta("Sales Order").has_field("quotation_reference")): return None
    return frappe.db.get_value("Sales Order", sales_order, "quotation_reference")


def apply_row_quantities(ciModels, resolved: Dict[str, float]):
    """ADR-0001 D1 - every formula in boq_format.JSON multiplies by cartQty, so
    swapping that for the OPR row quantity is all it takes to size the sheet to
    this release."""
    for model in ciModels:
        cart_item = (model.get("cartItemId") or {}).get("value")
        if(cart_item not in resolved): continue
        quantity = resolved[cart_item]
        model["cartQty"] = {"value": quantity}
        model["qty"] = {"value": f"{quantity:,.2f}"}


def get_opr_details(opr) -> Dict:
    return {
        "name": opr.name,
        "customer_name": opr.customer_name,
        "sales_order": opr.sales_order or "",
        "project": opr.project or "",
        "docstatus": opr.docstatus,
        "water_mark": " " if opr.docstatus == 1 else "DRAFT",
    }
