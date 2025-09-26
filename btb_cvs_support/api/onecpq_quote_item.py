import frappe
from .btb_quotation import *
#DEV API Key = dd017c3d9d14afe:2aba5089f049917


@frappe.whitelist()
def get_quotation_items(quote_name: str,currency:str,visibleFields:str):
    print('quote_name : ',quote_name)
    print('quote_name currency : ',currency)
    # frappe.log(visibleFields)
    items = get_synced_items(quote_name)
    count = 1
    headers=json.loads(visibleFields)
    for item in items: 
        item["idx"] = count
        item.qty = f"{item.qty:,.0f}"
        if( "actual_qty" in item): item.actual_qty = f"{item.actual_qty:,.0f}"
        if( "company_total_stock" in item): item.company_total_stock = f"{item.company_total_stock:,.0f}"
        item.amount = f"{item.amount:,.2f}"
        item.net_amount = f"{item.net_amount:,.2f}"
        item.rate = f"{item.rate:,.2f}"
        item.net_rate = f"{item.net_rate:,.2f}"
        if(not ("custom_tag_ref" in item) or item["custom_tag_ref"] == None): item["custom_tag_ref"] = ''
        if(not ("tag_ref" in item) or item["tag_ref"] == None): item["tag_ref"] = ''
        if(not ("notes" in item) or item["notes"] == None): item["notes"] = ''
        if(not ("description" in item) or item["description"] == None): item["description"] = ''
        count += 1
    return frappe.frappe.render_template("btb_cvs_support/api/onecpq_quote_item.html", {"items": items,"currency":currency,"headers":headers})

@frappe.whitelist()
def get_quotation_onecpq_total(quote_name: str,currency:str):
    print('quote_name : ',quote_name)
    print('quote_name currency : ',currency)
    quote = getQuoteById(quote_name)
    if(quote != None): 
        discAmt = quote.custom_list_amount - quote.total
        quote.discountAmount = f"{discAmt:,.2f}"
        quote.custom_list_amount = f"{quote.custom_list_amount:,.2f}"
        quote.custom_discount = f"{quote.custom_discount:,.2f}"
        quote.total = f"{quote.total:,.2f}"
        quote.additional_discount_percentage = f"{quote.additional_discount_percentage:,.2f}"
        quote.discount_amount = f"{quote.discount_amount:,.2f}"
        quote.net_total = f"{quote.net_total:,.2f}"
        quote.custom_total_discount = f"{quote.custom_total_discount:,.2f}"
        quote.custom_total_discount_amount = f"{quote.custom_total_discount_amount:,.2f}"
        return frappe.frappe.render_template("btb_cvs_support/api/onecpq_quote_total.html", {"cpqTotal": quote,"currency":currency})
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
