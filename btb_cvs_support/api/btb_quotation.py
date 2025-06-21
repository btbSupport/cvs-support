import frappe
import json
from typing import Dict, List
import pandas as pd
from erpnext.controllers.taxes_and_totals import calculate_taxes_and_totals
fti_cache ={}

def populate_cart_item_model( quote_name):
    cartItems = get_synced_cart_items(quote_name)
    populate_featuretype_items(cartItems)
    return populate_cart_models(cartItems)


@frappe.whitelist()
def get_synced_cart_items( quote_name: str) -> List[Dict[str, any]]:
    sql = f""" select tbc.name,tbc.Unit_Price,tbc.discount , tbc.Sequence, tbc.Quantity, tbc.Title,
        i.Name itemName, i.item_code, tbf.Field, tbf.label ,
        tbcif.value cif_value,tbfti.value fti_value,tbfti.`object` obj_value,tbft.object_type obj_type,tbft.data_text_field 
    from tabBtbCartItem tbc
    join `tabItem` i on tbc.item  = i.name and   tbc.name in (
    select custom_cart_item from `tabQuotation Item` where parent='{quote_name}'
    )
    join tabBtbCartItemFeature tbcif on tbcif.parent = tbc.name
    join tabBtbFeature tbf  on tbf.name = tbcif.feature 
    left join tabBtbFeatureTypeItem tbfti on tbcif.value = tbfti.name
    left join tabBtbFeatureType tbft on tbft.name = tbfti.feature_type
    """
    items = frappe.db.sql(sql, as_dict=1)
    df = pd.DataFrame(json.loads(json.dumps(items)))
    res = df.groupby(["name","Unit_Price","discount","Sequence","Quantity","Title","itemName","item_code"], group_keys=False)
    return res

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
                item =  {
                "cartProductName": {"value": row.itemName},
                "cartProductCode": {"value": row.item_code},
                "qty": {"value": row.Quantity},
                "unitPrice": {"value": row.Unit_Price},
                "beforeDiscount": {"value":  row.Quantity * row.Unit_Price },
                "rate": {"value": row.Unit_Price*(1-(row.discount/100))},
                "amount": {"value": row.Unit_Price*(1-(row.discount/100))*row.Quantity},
                "seq": {"value": row.Sequence}
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
    frappe.log(sql)
    result = frappe.db.sql(sql, as_dict=1)
    for i in result:
        fti_cache[fti] = i[data_text_field]

@frappe.whitelist()
def get_synced_items(quote_name: str):
    sql = f"""
        select tqi.*,tbci.idx,tbci.unit_price,tbci.discount ciDiscount,tbci.quantity ciQty  from `tabQuotation Item` tqi join tabBtbCartItem tbci on tbci.name=tqi.custom_cart_item  where tqi.parent ='{quote_name}'
order by tbci.idx
    """
    items = frappe.db.sql(sql, as_dict=1)
    return items

@frappe.whitelist()
def getQuoteById( quote_name):
    sql = f"""
		select *  from `tabQuotation` tqi where name ='{quote_name}'
	"""
    return frappe.db.sql(sql, as_dict=1)[0]


@frappe.whitelist()
def applyDiscount( quote_name: str,discount:float):
    cartItems = get_cart_items(quote_name)
    print(cartItems)
    for item in cartItems:
        item = frappe.frappe.get_doc("BtbCartItem", item.name)
        item.discount = discount
        item.save()
    items = get_synced_items(quote_name)
    doc = frappe.frappe.get_doc("Quotation", quote_name)
    totalUnitPrice = 0
    totalLineDiscount = 0
    totalDiscountPercenatge = 0
    totalLineDiscountPercentage = 0
    for item in items: 
        totalUnitPrice += (item.ciQty * item.unit_price)
        totalLineDiscount +=  (item.ciQty * ((item.unit_price) * item.ciDiscount/100))
    totalDiscount = totalLineDiscount + doc.discount_amount
    if(totalUnitPrice>0) : 
        totalDiscountPercenatge = (totalDiscount/totalUnitPrice) * 100
        totalLineDiscountPercentage = (totalLineDiscount/totalUnitPrice) * 100
    doc.custom_list_amount = totalUnitPrice
    doc.custom_discount = totalLineDiscountPercentage
    doc.custom_total_discount_amount = totalDiscount
    doc.custom_total_discount = totalDiscountPercenatge
    calculate_taxes_and_totals(doc)

@frappe.whitelist()
def get_cart_items( quote_name: str) :
    sql = f""" select name,discount
    from tabBtbCartItem tbc where tbc.cart in (
    select parent from `tabBtbCartLink` where entity='{quote_name}'
    )
    
    """
    items = frappe.db.sql(sql, as_dict=1)
    return items