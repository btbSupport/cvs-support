import frappe
from .btb_quotation import *
#DEV API Key = dd017c3d9d14afe:2aba5089f049917


@frappe.whitelist()
def get_quotation_items(quote_name: str,currency:str):
    print('quote_name : ',quote_name)
    print('quote_name currency : ',currency)
    items = get_synced_items(quote_name)
    count = 1
    for item in items: 
        item["idx"] = count
        count += 1
    return frappe.frappe.render_template("btb_cvs_support/api/onecpq_quote_item.html", {"items": items,"currency":currency})

def get_synced_items(quote_name: str):
    sql = f"""
        select tqi.*,tbci.idx,tbci.unit_price,tbci.discount ciDiscount  from `tabQuotation Item` tqi join tabBtbCartItem tbci on tbci.name=tqi.custom_cart_item  where tqi.parent ='{quote_name}'
order by tbci.idx
    """
    items = frappe.db.sql(sql, as_dict=1)
    return items

@frappe.whitelist()
def get_quotation_onecpq_total(quote_name: str,currency:str):
    print('quote_name : ',quote_name)
    print('quote_name currency : ',currency)
    items = get_synced_items(quote_name)
    quote = getQuoteById(quote_name)
    quote["totalUnitPrice"] = 0
    quote["totalLineDiscount"] = 0
    for item in items: 
        quote["totalUnitPrice"] += item.unit_price
        quote["totalLineDiscount"] +=  ((item.unit_price) * item.ciDiscount/100)
    if(len(items) >0) : quote["totalLineDiscountPercentage"] = (quote["totalLineDiscount"]/quote["totalUnitPrice"])*100
    else : quote["totalLineDiscountPercentage"] = 0
    return frappe.frappe.render_template("btb_cvs_support/api/onecpq_quote_total.html", {"cpqTotal": quote,"currency":currency})
