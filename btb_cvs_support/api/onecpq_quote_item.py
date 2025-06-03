import frappe
#DEV API Key = dd017c3d9d14afe:2aba5089f049917


@frappe.whitelist()
def get_quotation_items(quote_name: str):
    print('quote_name : ',quote_name)
    items = get_items(quote_name)
    count = 1
    total = 0
    for item in items: 
        item["idx"] = count
        count += 1
    return frappe.frappe.render_template("btb_cvs_support/api/onecpq_quote_item.html", {"items": items})

@frappe.whitelist()
def get_items(quote_name: str):
    sql = f"""
        select tqi.*,tbci.idx   from `tabQuotation Item` tqi join tabBtbCartItem tbci on tbci.name=tqi.custom_cart_item  where tqi.parent ='{quote_name}'
order by tbci.idx
    """
    items = frappe.db.sql(sql, as_dict=1)
    return items