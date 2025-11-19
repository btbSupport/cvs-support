import frappe
import json
from typing import Dict, List
import pandas as pd
from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals
from decimal import Decimal
from onecpq_connect.api.functions import bulk_insert_with_children
fti_cache ={}

def populate_cart_item_model( quote_name):
    syncedItems = get_synced_cart_items(quote_name)
    if(len(syncedItems)==0): return None
    cartItems = get_grouped_items(syncedItems)
    populate_featuretype_items(cartItems)
    return populate_cart_models(cartItems)

def get_grouped_items(items):
    df = pd.DataFrame(json.loads(json.dumps(items)))
    res = df.groupby(["name","Unit_Price","discount","Sequence","Quantity","Title","itemName","item_code"], group_keys=False)
    return res
@frappe.whitelist()
def get_synced_cart_items( quote_name: str) -> List[Dict[str, any]]:
    sql = f""" select tbc.name,tbc.Unit_Price,tbc.discount , tbc.Sequence, tbc.Quantity, tbc.Title,
        i.Name itemName, i.item_code, tbf.Field, tbf.label ,
        tbcif.value cif_value,tbfti.value fti_value,tbfti.`object` obj_value,tbft.object_type obj_type,tbft.data_text_field 
    from tabBtbCartItem tbc
    join `tabItem` i on tbc.item  = i.name and   tbc.name in (
    select parent from tabBtbCartItemLink tbcil where entity = '{quote_name}'
    )
    join tabBtbCartItemFeature tbcif on tbcif.parent = tbc.name
    join tabBtbFeature tbf  on tbf.name = tbcif.feature 
    left join tabBtbFeatureTypeItem tbfti on tbcif.value = tbfti.name
    left join tabBtbFeatureType tbft on tbft.name = tbfti.feature_type
    order by tbc.idx
    """
    items = frappe.db.sql(sql, as_dict=1)
    return items

def populate_featuretype_items( cartItems):
    for group_name, df_group in cartItems:
        ftis =  {}
        for row_index, row in df_group.iterrows():
            if(row.obj_type != None):
                key = str(row.obj_type)+'-'+str(row.data_text_field)+'-'+str(row.cif_value)
                if( key not in ftis.keys()):ftis[key] = []
                if( row.obj_value not in fti_cache.keys()):ftis[key].append(row.obj_value)
        for key in ftis.keys():
            # print("check ",key)
            if(key == None): continue
            fti = ftis.get(key)
            obj = key.split("-")
            if(obj[0] !='') : get_featuretype_items(obj[0],obj[1],fti,obj[2])

def populate_cart_models( cartItems: Dict[str,any]) -> List[Dict[str, Dict]]:
    output =[]
    # print('fti_cache : ',fti_cache)
    for group_name, df_group in cartItems:
        item =  {}
        for row_index, row in df_group.iterrows():
            if(item == {}):
                # item =  {
                # "cartProductName": {"value": row.itemName},
                # "cartProductCode": {"value": row.item_code},
                # "qty": {"value":  round(Decimal(str(row.Quantity)),0)},
                # "unitPrice": {"value": round(Decimal(str(row.Unit_Price)),2)},
                # "beforeDiscount": {"value":   round(Decimal(str(row.Quantity * row.Unit_Price)),2)},
                # "rate": {"value":  round(Decimal(str(row.Unit_Price*(1-(row.discount/100)))),2)},
                # "amount": {"value":  round(Decimal(str(row.Unit_Price*(1-(row.discount/100))*row.Quantity)),2)},
                # "seq": {"value": row.Sequence},
                # "cartTitle": {"value": row.Title},
                # }
                item =  {
                "cartProductName": {"value": row.itemName},
                "cartProductCode": {"value": row.item_code},
                "qty": {"value":   f"{row.Quantity:,.2f}"},
                "cartQty": {"value":   row.Quantity},
                "unitPrice": {"value": f"{row.Unit_Price:,.2f}"},
                "beforeDiscount": {"value":   f"{(row.Quantity * row.Unit_Price):,.2f}"},
                "rate": {"value":  f"{(row.Unit_Price*(1-(row.discount/100))):,.2f}"},
                "cartAmount": {"value": (row.Unit_Price*(1-(row.discount/100))*row.Quantity)},
                "amount": {"value": f"{(row.Unit_Price*(1-(row.discount/100))*row.Quantity):,.2f}"},
                "seq": {"value": row.Sequence},
                "cartTitle": {"value": row.Title},
                }
            value = row.cif_value
            if(row.fti_value != None):value = row.fti_value
            if(row.obj_type != None):value = fti_cache.get(row.cif_value)
            item[row.Field]={"label": row.label, "value": value}
        output.append(item)
    return output  
def get_featuretype_items( tabName:str, data_text_field:str, values: List[str],fti:str):
    sql = f"""
    select * from `tab{tabName}` where name in {'',''.join(values)}
    """
    # frappe.log(sql)
    result = frappe.db.sql(sql, as_dict=1)
    for i in result:
        fti_cache[fti] = i[data_text_field]

@frappe.whitelist()
def get_synced_cart_items(quote_name: str):
    sql = f"""
        select tbci.*,i.item_name, i.item_code,sequence,i.stock_uom,i.description  from `tabBtbCartItemLink` tqi 
        join tabBtbCartItem tbci on tbci.name=tqi.parent  
		join `tabItem` i on tbci.item = i.name
        where tqi.entity ='{quote_name}'
order by tbci.idx
    """
    items = frappe.db.sql(sql, as_dict=1)
    return items

@frappe.whitelist()
def get_synced_items(quote_name: str):
    sql = f"""
        select tqi.*,tbci.idx,tbci.unit_price,tbci.discount ciDiscount,tbci.quantity ciQty,tbci.name ciName  from `tabQuotation Item` tqi 
        join tabBtbCartItem tbci on tbci.name=tqi.custom_cart_item  where tqi.parent ='{quote_name}'
order by tbci.idx
    """
    items = frappe.db.sql(sql, as_dict=1)
    return items

@frappe.whitelist()
def getQuoteById( quote_name):
    sql = f"""
		select *  from `tabQuotation` tqi where name ='{quote_name}'
	"""
    items = frappe.db.sql(sql, as_dict=1)
    if(len(items) >0) : return items[0]
    return None


@frappe.whitelist()
def applyDiscount( quote_name: str,discount:float):
    cartItems = get_cart_items(quote_name)
    # print(cartItems)
    for item in cartItems:
        item = frappe.frappe.get_doc("BtbCartItem", item.name)
        item.discount = discount
        item.db_update()
    sync_all(quote_name)
    # items = get_synced_items(quote_name)
    # doc = frappe.frappe.get_doc("Quotation", quote_name)
    # doc.save()
    # totalUnitPrice = 0
    # totalLineDiscount = 0
    # totalDiscountPercenatge = 0
    # totalLineDiscountPercentage = 0
    # for item in items: 
    #     totalUnitPrice += (item.ciQty * item.unit_price)
    #     totalLineDiscount +=  (item.ciQty * ((item.unit_price) * item.ciDiscount/100))
    # totalDiscount = totalLineDiscount + doc.discount_amount
    # if(totalUnitPrice>0) : 
    #     totalDiscountPercenatge = (totalDiscount/totalUnitPrice) * 100
    #     totalLineDiscountPercentage = (totalLineDiscount/totalUnitPrice) * 100
    # doc.custom_list_amount = totalUnitPrice
    # doc.custom_discount = totalLineDiscountPercentage
    # doc.custom_total_discount_amount = totalDiscount
    # doc.custom_total_discount = totalDiscountPercenatge
    # calculate_taxes_and_totals(doc)

# @frappe.whitelist()
# def lock_cart( quote_name: str, lock:bool) :
#     sql = f""" select parent from `tabBtbCartLink` cl join `tabBtbCart` c on cl.parent = c.name and c.locked !='{lock}' 
#     where entity='{quote_name}'
#     """
#     items = frappe.db.sql(sql, as_dict=1)
#     for item in items:
#         cart = frappe.frappe.get_doc("BtbCart", item.parent)
#         cart.locked = lock
#         cart.save()

@frappe.whitelist()
def get_cart_items( quote_name: str) :
    sql = f""" select name,discount
    from tabBtbCartItem tbc where tbc.cart in (
    select parent from `tabBtbCartLink` where entity='{quote_name}'
    )
    order by tbc.idx
    
    """
    items = frappe.db.sql(sql, as_dict=1)
    return items

# @frappe.whitelist()
# def amendCPQ(quote_name: str,amended_from: str):
#     print('inside amendCPQ',quote_name)
#     print('inside amendCPQ amended_from',amended_from)
#     cart_name = create_cart(quote_name)
#     cartItems = get_synced_items(amended_from)
#     print('inside amendCPQ cartItems',cartItems)
#     # clonedItems=[]
#     seq = 1
#     for item in cartItems:
#         cartItem = frappe.frappe.get_doc("BtbCartItem", item.ciName)
#         cartItem.name = None
#         cartItem.cart = cart_name
#         cartItem.idx = seq
#         seq +=1
#         ciLinks =[]
#         for cil in cartItem.cart_item_links:
#             cil.entity = quote_name
#             ciLinks.append(cil)
#         cartItem.cart_item_links = ciLinks
#         # cartItem.cart_item_links =[]
#         cartItem.save()
#     quot = frappe.frappe.get_doc("Quotation", quote_name)
#     quot.custom_cpq_amended = 1
#     quot.db_update()

@frappe.whitelist()
def amendCPQ(quote_name: str,amended_from: str):
    print('inside amendCPQ',quote_name)
    print('inside amendCPQ amended_from',amended_from)
    cart_name = create_cart(quote_name)
    syncedItems = get_synced_items(amended_from)
    print('inside amendCPQ cartItems',syncedItems)
    cartItems = []
    seq = 1
    quoteItemMap = {}
    for item in syncedItems:
        ci = frappe.get_doc("BtbCartItem", item.ciName)
        # ci.name = None
        quoteItemMap[item.ciName] = frappe.frappe.get_doc("Quotation Item",item.name)
        ci.cart = cart_name
        ci.idx = seq
        seq +=1
        ciLinks =[]
        for cil in ci.cart_item_links:
            cil.entity = quote_name
            ciLinks.append(cil)
        ci.cart_item_links = ciLinks
        cartItems.append(ci)
    items = bulk_insert_with_children("BtbCartItem",cartItems)
    qliId = 1
    quot = frappe.frappe.get_doc("Quotation", quote_name)
    quoteItems = []
    for key in list(items['parents'].keys()):
        quoteItem = quoteItemMap[key]
        quoteItem.custom_cart_item = items['parents'][key]
        quoteItem.idx = qliId
        quoteItem.name = None
        quoteItem.parent = quote_name
        qliId +=1
        quoteItem.db_update()
        # quoteItems.append(quoteItem)
    quot.custom_cpq_amended = 1
    # quot.items = quoteItems
    # calculate_taxes_and_totals(quot)
    quot.db_update()
    print('inside amendCPQ amended')
    return 'Cart Amended'


def create_cart(quote_name: str):
    cartLink = frappe.new_doc("BtbCartLink")
    cartLink.entity_type = "Quotation"
    cartLink.entity = quote_name
    cart = frappe.new_doc("BtbCart")
    cart.append('cart_links', cartLink)
    cart.insert()
    return cart.name

@frappe.whitelist()
def sync_all(quote_name, method = None):
    cartsql = f"""select parent from tabBtbCartLink tbcl where entity ='{quote_name}'"""
    cart = frappe.db.sql(cartsql, as_dict=1)[0].parent
    sql = f""" select tbc.name 
    from tabBtbCartItem tbc where tbc.cart = '{cart}' and tbc.name not in (
    select parent from tabBtbCartItemLink tbcil where entity = '{quote_name}'
    )"""
    # qitems = []
    # sql = f"""
	# 	select name,conversion_rate  from `tabQuotation` tqi where name ='{quote_name}'
	# """
    # qt= frappe.db.sql(sql, as_dict=1)[0]
    for item in frappe.db.sql(sql, as_dict=1): 
        ci = populate_cart_item_links(quote_name, item)
        ci.db_insert()
    # cartItems = get_all_cart_items(cart)
    # for item in cartItems: 
    #     quoteItem = frappe.frappe.new_doc("Quotation Item")
    #     quoteItem = populate_quotation_item(quoteItem, ci, qt)
    #     quoteItem.db_insert()
    #     qitems.append(quoteItem)
    quote = frappe.frappe.get_doc("Quotation", quote_name)
    # quote.items = qitems
    # calculate_taxes_and_totals(quote)
    quote.save()

def get_all_cart_items(name:str):
	sql = f"""
		select ci.name, item, price_list, list_price, unit_price, quantity, discount,
			i.item_name, i.item_code,sequence,i.stock_uom,ci.idx,i.description
		from `tabBtbCartItem` ci
		join `tabItem` i on ci.item = i.name
		where ci.cart = '{name}'
	"""
	print("Trying to fetch cart item", sql)
	return frappe.db.sql(sql, as_dict=1)

def populate_cart_item_links(quote_name:str,item:any):
    ci = frappe.frappe.new_doc("BtbCartItemLink")
    ci.entity = quote_name
    ci.entity_type = "Quotation"
    ci.parent = item.name
    ci.parenttype = "BtbCartItem"
    ci.parentfield = "cart_item_links"
    return ci

def populate_quotation_item(doc, cartItem, qt):
	
	doc.parenttype = 'Quotation'
	doc.parent = qt.name
	doc.parentfield= "items"
	doc.uom = cartItem.stock_uom
	doc.conversion_factor = 1
	doc.item_code = cartItem.item
	doc.item_name = cartItem.item_name
	doc.qty = cartItem.quantity
	doc.base_price_list_rate = cartItem.list_price
	doc.price_list_rate = cartItem.list_price / qt.conversion_rate
	doc.base_rate = cartItem.unit_price -  (cartItem.discount * cartItem.unit_price/100)
	doc.rate = doc.base_rate / qt.conversion_rate
	doc.base_amount = cartItem.quantity * doc.base_rate
	doc.amount = doc.base_amount / qt.conversion_rate
	doc.idx = cartItem.idx
	doc.description = cartItem.description
	# doc.discount_percentage = cartItem.discount
	# doc.discount_amount = cartItem.discount * cartItem.unit_price
	doc.custom_cart_item = cartItem.name
	return doc