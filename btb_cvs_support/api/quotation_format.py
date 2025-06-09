
import json
import re
from decimal import Decimal
from typing import Dict, List, Union
import frappe
import os
import pandas as pd
import numpy as np
from ..document.generator import *


def decimal_serializer(obj):
    if isinstance(obj, Decimal):
        return str(round(obj,2))
    raise TypeError('Type not serializable + '+obj)
# class quotation_format:
fti_cache ={}
# def provide( params: Dict[str, str]) -> Dict:
#     quote_id = params.get("Id")
#     return populate_cart_items(quote_id)
@frappe.whitelist()
def provide( quote_name: str) -> Dict:
    output = {"ci": {
        "cartItem": populate_cart_detail(quote_name),
        "companyInfo": get_company_info()
    },
    "qt": get_quote_details(quote_name)
    }
    print("result -", output)
    file_path = "../apps/btb_cvs_support/btb_cvs_support/document/templates/quotation.docx"
    # generate("templates/quotation.docx", json.loads(json.dumps(output)), format="pdf")
    generate(file_path, output, format="pdf",doc_type="Quotation",doc_name=quote_name,file_name="QuotationFormat_"+quote_name+".pdf")

    return json.loads(json.dumps(output,default=decimal_serializer))

def get_quote_details( quote_name: str) -> Dict:
    sql = f""" select customer_name,address_display,contact_display,contact_designation,contact_mobile,contact_email,subject,project,name,terms,quotation_term_details,letter_details,standard_tc_details,grand_total,total_taxes_and_charges,net_total,discount_amount,additional_discount_percentage,total  from `tabQuotation` tqi where name ='{quote_name}'
    """
    items = frappe.db.sql(sql, as_dict=1)
    items[0]["grand_total"]=get_decimal(items[0]["grand_total"])
    items[0]["total_taxes_and_charges"]=get_decimal(items[0]["total_taxes_and_charges"])
    items[0]["net_total"]=get_decimal(items[0]["net_total"])
    items[0]["discount_amount"]=get_decimal(items[0]["discount_amount"])
    items[0]["additional_discount_percentage"]=get_decimal(items[0]["additional_discount_percentage"])
    items[0]["total"]=get_decimal(items[0]["total"])
    return items[0]

def get_company_info() -> Dict:
    sql = f""" select name,default_currency ,email  from tabCompany tc 
    """
    items = frappe.db.sql(sql, as_dict=1)
    return {
        "Email": items[0].email,
        "currency": items[0].default_currency,
        "name": items[0].name
    }



def populate_product_family_map() -> Dict[str, 'ProductInfo']:
    base_path = os.path.dirname(__file__)  # Path to the current .py file
    file_path = os.path.join(base_path, 'quote_format.json')
    with open(file_path, 'r') as f:
        setting_json = json.load(f)
    # with open('./quote_format.JSON') as quote_format_file:
    #     setting_json = quote_format_file.read()
    return json.loads(json.dumps(setting_json))

class ProductInfo:
    def __init__( headerKey: str, header: Dict[str, str], detail: str, summary: str):
        headerKey = headerKey
        header = header
        detail = detail
        summary = summary

class ProductRootNode:
    def __init__(self, prd_name: str, prd_code: str):
        self.productCode = prd_code
        self.productName = prd_name
        self.productTotal = 0
        self.totalqty = 0
        self.items = {}

class ChildNode:
    def __init__(self):
        self.modelName = ""
        self.headers = []
        self.headersDisplay = []
        self.details = []
        self.summary = {}

class Display:
    def __init__( self,left, right):
        self.leftlabel = left["label"]
        self.rightlabel = right["label"]
        self.leftValue = left.get("value", "N/A") or "N/A"
        self.rightValue = right.get("value", "N/A") or "N/A"

def get_prefix( val: str) -> str:
    return val.zfill(6)

def get_key( features: Dict[str, Dict], key: str) -> str:
    return "-".join(str(features[k]["value"]) for k in key.split(",") if k in features)

def get_decimal( val) -> Decimal:
    try:
        return round(Decimal(str(val)),2)
    except:
        return Decimal(0)
@frappe.whitelist()
def populate_cart_detail( quote_id: str) -> Dict[str, 'ProductRootNode']:
    # print('inside populate cart')
    output = {}
    product_family_map = populate_product_family_map()
    keys = {}
    child_keys = {}

    cartItems = get_cart_items(quote_id)
    populate_featuretype_items(cartItems)
    models = populate_cart_models(cartItems)
    # print(models)
    for cart_model in models:
        product_code = get_key(cart_model, 'cartProductCode')
        sub_category = get_key(cart_model, 'subcategory')
        root_key = f"{product_code}-{sub_category}"

        if root_key not in keys:
            prefix = get_prefix(str(len(keys)))
            keys[root_key] = f"{prefix}{root_key}"
            output[keys[root_key]] = ProductRootNode(sub_category, product_code).__dict__

        prd_root_node = output[keys[root_key]]
        model_group_node = prd_root_node.get('items')
        group_key = get_key(cart_model, product_family_map[product_code]['headerKey'])

        if group_key not in child_keys:
            prefix = get_prefix(str(len(child_keys)))
            child_keys[group_key] = f"{prefix}{group_key}"
            c_node = ChildNode().__dict__
            c_node["modelName"] = get_key(cart_model, 'modelDescription')
            c_node["headers"] = populate_header_values(cart_model, product_family_map[product_code]['header'])
            c_node["headersDisplay"] = populate_header_display(c_node.get("headers"))
            c_node["details"] = []
            c_node["summary"] = {}
            model_group_node[child_keys[group_key]] = c_node

        model_group_node[child_keys[group_key]]["details"].append(
            populate_detail(cart_model, product_family_map[product_code]['detail'])
        )
        model_group_node[child_keys[group_key]]["summary"] = populate_summary(
            cart_model,
            product_family_map[product_code]['summary'],
            model_group_node[child_keys[group_key]]["summary"]
        )
        prd_root_node["productTotal"] += get_decimal(get_key(cart_model, 'beforeDiscount'))
        prd_root_node["totalqty"] += round(get_decimal(get_key(cart_model, 'qty')),0)
        prd_root_node["items"] = model_group_node
    return output

def populate_header_values( features, header_map):
    output = []
    for label, field in header_map.items():
        val = str(populate_value(features, field)) or 'N/A'
        output.append({"label": label, "value": val})
    return output

def populate_header_display( headers: List[Dict]) -> List['Display']:
    output = []
    for i in range(0, len(headers), 2):
        if i+1 < len(headers):
            output.append(Display(headers[i], headers[i+1]).__dict__)
    return output

def populate_detail( features, keys) -> Dict:
    return {k: features[k]["value"] for k in keys.split(",") if k in features}

def populate_summary( features, keys, summ: Dict) -> Dict:
    for k in keys.split(","):
        if k in features:
            summ[k] = summ.get(k, Decimal(0)) + get_decimal(features[k]["value"])
            if(k=='qty') : summ[k] = round(summ[k],0)
    return summ

def populate_value( features, formula: str) -> Union[str, Decimal]:
    if not formula.startswith("CONCAT"):
        return features.get(formula, {}).get("value", "")
    keys = exec(formula)
    return "".join([features.get(k, {}).get("value", "") if "string" not in k else k.replace("string", "") for k in keys])

def exec( formula) -> List[str]:
    match = re.search(r'CONCAT\((.*?)\)', formula)
    if match:
        return match.group(1).split(',')
    return []

def populate_cart_models( cartItems: Dict[str,any]) -> List[Dict[str, Dict]]:
    output =[]
    # print('fti_cache : ',fti_cache)
    for group_name, df_group in cartItems:
        # print ('inside 1st loop')
        item =  {}
        for row_index, row in df_group.iterrows():
            # print ('loop2')
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
    # print("output final - ",output)
    return output   

def get_cart_items( quote_id: str) -> List[Dict[str, any]]:
    # print('inside get cart items')
    sql = f""" select tbc.name,tbc.Unit_Price,tbc.discount , tbc.Sequence, tbc.Quantity, tbc.Title,
        i.Name itemName, i.item_code, tbf.Field, tbf.label ,
        tbcif.value cif_value,tbfti.value fti_value,tbfti.`object` obj_value,tbft.object_type obj_type,tbft.data_text_field 
    from tabBtbCartItem tbc
    join `tabItem` i on tbc.item  = i.name and   tbc.name in (
    select custom_cart_item from `tabQuotation Item` where parent='{quote_id}'
    )
    join tabBtbCartItemFeature tbcif on tbcif.parent = tbc.name
    join tabBtbFeature tbf  on tbf.name = tbcif.feature 
    left join tabBtbFeatureTypeItem tbfti on tbcif.value = tbfti.name
    left join tabBtbFeatureType tbft on tbft.name = tbfti.feature_type
    """
    items = frappe.db.sql(sql, as_dict=1)

    # with open('sample_cart_item.csv') as sample_file:
    #     items = sample_file.read()
    # print('result cart items ',items)
    df = pd.DataFrame(json.loads(json.dumps(items)))
    
    # df = pd.read_csv('sample_cart_item.csv')
    res = df.groupby(["name","Unit_Price","discount","Sequence","Quantity","Title","itemName","item_code"], group_keys=False)
    # print(df.groupby(["name","Unit_Price","discount","Sequence","Quantity","Title","itemName","item_code"]))
    # print(items.get_group('CI30583'))
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
            get_featuretype_items(obj[0],obj[1],fti,obj[2])

def get_featuretype_items( tabName:str, data_text_field:str, values: List[str],fti:str):
    sql = f"""
    select * from `tab{tabName}` where name in {'',''.join(values)}
    """
    # print("sql - ",sql)
    result = frappe.db.sql(sql, as_dict=1)
    for i in result:
        fti_cache[fti] = i[data_text_field]
    # print('fti_cache : ',fti_cache)