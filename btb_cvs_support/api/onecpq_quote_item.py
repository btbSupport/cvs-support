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

@frappe.whitelist()
def get_quotation_onecpq_total(quote_name: str,currency:str):
    print('quote_name : ',quote_name)
    print('quote_name currency : ',currency)
    quote = getQuoteById(quote_name)
    if(quote != None): return frappe.frappe.render_template("btb_cvs_support/api/onecpq_quote_total.html", {"cpqTotal": quote,"currency":currency})
    return None

# @frappe.whitelist()
# def get_quotation_onecpq_total(quote_name: str,currency:str):
#     print('quote_name : ',quote_name)
#     print('quote_name currency : ',currency)
#     items = get_synced_items(quote_name)
#     quote = getQuoteById(quote_name)
#     quote["totalUnitPrice"] = 0
#     quote["totalLineDiscount"] = 0
#     quote["totalLineDiscountPercentage"] = 0
#     quote["totalDiscountPercentage"] = 0
#     for item in items: 
#         quote["totalUnitPrice"] += (item.ciQty * item.unit_price)
#         quote["totalLineDiscount"] +=  (item.ciQty * ((item.unit_price) * item.ciDiscount/100))

#     quote["totalDiscountAmount"] = quote["totalLineDiscount"] + quote["discount_amount"]
#     if(quote["totalUnitPrice"] >0) : 
#         quote["totalLineDiscountPercentage"] = (quote["totalLineDiscount"]/quote["totalUnitPrice"])*100
#         quote["totalDiscountPercentage"] = (quote["totalDiscountAmount"]/quote["totalUnitPrice"])*100
#     return frappe.frappe.render_template("btb_cvs_support/api/onecpq_quote_total.html", {"cpqTotal": quote,"currency":currency})
