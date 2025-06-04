import frappe
from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals
#DEV API Key = dd017c3d9d14afe:2aba5089f049917

@frappe.whitelist()
def get_synced_items(quote_name: str):
    sql = f"""
        select tqi.*,tbci.idx   from `tabQuotation Item` tqi join tabBtbCartItem tbci on tbci.name=tqi.custom_cart_item  where tqi.parent ='{quote_name}'
order by tbci.idx
    """
    items = frappe.db.sql(sql, as_dict=1)
    return items
@frappe.whitelist()
def get_cart_item_links(quote_name: str):
    sql = f"""select name from tabBtbCartItemLink where entity='{quote_name}'"""
    items = frappe.db.sql(sql, as_dict=1)
    return items

@frappe.whitelist()
def get_cart_items(quote_name: str):
    sql = f"""select * from tabBtbCartItem tbci where parent in (select parent  from tabBtbCartLink tbcl where entity ='{quote_name}') and valid = 1 
and name not in (select custom_cart_item from `tabQuotation Item` tqi where tqi.parent ='{quote_name}'  and custom_cart_item is not null)"""
    items = frappe.db.sql(sql, as_dict=1)
    return items

@frappe.whitelist()
def get_items(quote_name: str):
    sql = f"""
        select name from `tabQuotation Item` tqi   where tqi.parent ='{quote_name}' and tqi.custom_cart_item is null
    """
    items = frappe.db.sql(sql, as_dict=1)
    return items


@frappe.whitelist()
def remove_quotation_items(doc, method = None):
    quote_name = doc.name
    customizable = doc.custom_customizable
    print('inside remove quote_name :',quote_name,' customizable :',customizable)
    items = []
    cartItemLinks = []
    if(customizable == 1): 
        cartItems = get_cart_items(quote_name)
        print('cartItems :',cartItems)
        for item in cartItems: 
            ci = populate_cart_item_links(quote_name, item)
            ci.save()
        print('get_cart_item_links(quote_name) :', get_cart_item_links(quote_name))
        print('gte synced(quote_name) :', get_synced_items(quote_name))
        items = get_items(quote_name)
        print('items :',items)
        for item in items: 
            frappe.delete_doc("Quotation Item",item.name) == None
    if(customizable == 0) : 
        cartItemLinks = get_cart_item_links(quote_name)
        print(' cartItemLinks :',cartItemLinks)
        for item in cartItemLinks: 
            frappe.delete_doc("BtbCartItemLink",item.name) == None
    quoteOld = frappe.frappe.get_doc("Quotation", quote_name)
    quote = frappe.frappe.get_doc("Quotation", quote_name)
    calculate_taxes_and_totals(quote)
    if(quote.total != quoteOld.total): quote.save()

def populate_cart_item_links(quote_name:str,item:any):
    ci = frappe.frappe.new_doc("BtbCartItemLink")
    ci.entity = quote_name
    ci.entity_type = "Quotation"
    ci.parent = item.name
    ci.parenttype = "BtbCartItem"
    ci.parentfield = "cart_item_links"
    return ci

   
    

    