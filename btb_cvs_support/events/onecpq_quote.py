import frappe
from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals
from ..api.onecpq_quote_item import *
#DEV API Key = dd017c3d9d14afe:2aba5089f049917

@frappe.whitelist()
def delete_links(doc, method = None):
    sql = f"""select name from tabBtbCartItemLink where parent='{doc}'"""
    for item in frappe.db.sql(sql, as_dict=1): 
            frappe.delete_doc("BtbCartItemLink",item.name) == None
    return

@frappe.whitelist()
def get_cart_item_links(quote_name: str):
    sql = f"""select name from tabBtbCartItemLink where entity='{quote_name}'"""
    items = frappe.db.sql(sql, as_dict=1)
    return items

@frappe.whitelist()
def get_cart_items(quote_name: str):
    sql = f"""select * from tabBtbCartItem tbci where cart in (select parent  from tabBtbCartLink tbcl where entity ='{quote_name}') and valid = 1 
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

def before_save_cart(doc, method = None):
    if(doc.unit_price == 0): doc.valid = 0

def proceed_cart_item_link(doc, method = None):
    print('doc.unit_price : ',doc.unit_price)
    print('doc.valid : ',doc.valid)
    if(doc.unit_price == 0):
        sqlcil = f"""select name,entity from tabBtbCartItemLink where parent='{doc.name}'"""
        for item in frappe.db.sql(sqlcil, as_dict=1): 
            frappe.delete_doc("BtbCartItemLink",item.name) == None
        print('doc.valid after: ',doc.valid)
        return
    if(doc.valid == 1):
        sql = f"""select entity  from tabBtbCartLink tbcl where parent ='{doc.cart}'
        and entity not in (select entity from tabBtbCartItemLink where parent='{doc.name}')"""
        entityList = []
        for item in frappe.db.sql(sql, as_dict=1): 
            entityList.append(item.entity)
        for entity in entityList: 
            ci = populate_cart_item_links(entity, doc)
            ci.save()

@frappe.whitelist()
def before_save_quote(doc = None, method = None):
    beforequote = getQuoteById(doc.name)
    if(beforequote == None): return
    if(doc is None): return
    remove_quotation_items(doc)
    if(doc.custom_customizable == 1): 
        doc.apply_discount_on = 'Net Total'
        if(doc.additional_discount_percentage != doc.custom_cart_discount):
            doc.additional_discount_percentage = doc.custom_cart_discount
    doc.items = []
    syncItems = get_synced_items(doc.name)
    items = get_items(doc.name)

    print('doc before calc - items : ',syncItems)
    print('doc before calc - discount amount : ',doc.discount_amount)
    print('doc after calc - discount amount : ',doc.discount_amount)
    totalUnitPrice = 0
    totalLineDiscount = 0
    totalDiscountPercenatge = 0
    totalLineDiscountPercentage = 0

    for item in items: 
        doc.items.append(frappe.frappe.get_doc("Quotation Item", item.name))
    
    for item in syncItems: 
        totalUnitPrice += (item.ciQty * item.unit_price)
        totalLineDiscount +=  (item.ciQty * ((item.unit_price) * item.ciDiscount/100))
        doc.items.append(frappe.frappe.get_doc("Quotation Item", item.name))
    calculate_taxes_and_totals(doc)
    totalDiscount = totalLineDiscount + doc.discount_amount
    if(totalUnitPrice>0) : 
        totalDiscountPercenatge = (totalDiscount/totalUnitPrice) * 100
        totalLineDiscountPercentage = (totalLineDiscount/totalUnitPrice) * 100
    doc.custom_list_amount = totalUnitPrice
    doc.custom_discount = totalLineDiscountPercentage
    doc.custom_total_discount_amount = totalDiscount
    doc.custom_total_discount = totalDiscountPercenatge
    if(doc.custom_total_discount>32):frappe.throw('Total Discount % exceeds the approved limit.')
    print('doc after calc - items : ',doc.items)

@frappe.whitelist()
def remove_quotation_items(doc):
    quote_name = doc.name
    customizable = doc.custom_customizable
    print('inside remove quote_name :',quote_name,' customizable :',customizable)
    beforequote = getQuoteById(doc.name)
    if(beforequote == None): return
    if(customizable == beforequote.custom_customizable): return
    items = []
    cartItemLinks = []
    if(customizable == 1): 
        cartItems = get_cart_items(quote_name)
        for item in cartItems: 
            ci = populate_cart_item_links(quote_name, item)
            ci.save()
        items = get_items(quote_name)
        for item in items: 
            frappe.delete_doc("Quotation Item",item.name) == None
    if(customizable == 0) : 
        cartItemLinks = get_cart_item_links(quote_name)
        for item in cartItemLinks: 
            frappe.delete_doc("BtbCartItemLink",item.name) == None
    print("inside remove quote_name end 102",quote_name)

def populate_cart_item_links(quote_name:str,item:any):
    ci = frappe.frappe.new_doc("BtbCartItemLink")
    ci.entity = quote_name
    ci.entity_type = "Quotation"
    ci.parent = item.name
    ci.parenttype = "BtbCartItem"
    ci.parentfield = "cart_item_links"
    return ci
@frappe.whitelist()
def on_trash(doc, method = None):
    print('deleting cart',method)