
import json
import re
from decimal import Decimal
from typing import Dict, List, Union
import frappe
import os
import pandas as pd
import numpy as np
from ..document.generator import *
from .btb_quotation import *


def decimal_serializer(obj):
    if isinstance(obj, Decimal):
        return str(round(obj,2))
    raise TypeError('Type not serializable + '+obj)
fti_cache ={}

@frappe.whitelist()
def provide( quote_name: str) -> Dict:
    output = {"ci": {
        "cartItem": populate_cart_detail(quote_name),
        "companyInfo": get_company_info()
    },
    "qt": get_quote_details(quote_name)
    }
    # print("result -", output)
    file_path = "../apps/btb_cvs_support/btb_cvs_support/document/templates/quotation_format.docx"
    # generate("templates/quotation.docx", json.loads(json.dumps(output)), format="pdf")
    generate(file_path, output, format="pdf",doc_type="Quotation",doc_name=quote_name,file_name="QuotationFormat_"+quote_name+".pdf")
    # generate(file_path, output, format="original",doc_type="Quotation",doc_name=quote_name,file_name="QuotationFormat_"+quote_name+".docx")

    return json.loads(json.dumps(output,default=decimal_serializer))

def get_quote_details( quote_name: str) -> Dict:
    sql = f""" select customer_name,address_display,in_words,contact_display,contact_designation,contact_mobile,contact_email,subject,project,name,terms,quotation_term_details,letter_details,standard_tc_details,grand_total,total_taxes_and_charges,net_total,discount_amount,additional_discount_percentage,total  from `tabQuotation` tqi where name ='{quote_name}'
    """
    items = frappe.db.sql(sql, as_dict=1)
    item = items[0]
    item["grand_total"]=f"{(item['grand_total']):,.2f}"
    item["total_taxes_and_charges"]=f"{item['total_taxes_and_charges']:,.2f}"
    item["net_total"]=f"{item['net_total']:,.2f}"
    item["discount_amount"]=f"{item['discount_amount']:,.2f}"
    item["additional_discount_percentage"]=f"{item['additional_discount_percentage']:,.2f}"
    item["total"]=f"{item['total']:,.2f}"
    if(item["quotation_term_details"] != None):item["quotation_term_details"]='<div style="font-family:Helvetica Neue,sans-serif;font-size: 12px !important;">'+item["quotation_term_details"]+"</div>"

    if(item["standard_tc_details"] != None):item["standard_tc_details"]='<div style="font-family:Helvetica Neue,sans-serif;font-size: 12px !important;">'+item["standard_tc_details"]+"</div>"

    if(item["terms"] != None):item["terms"]='<div style="font-family:Helvetica Neue,sans-serif;font-size: 12px !important;">'+item["terms"]+"</div>"

    if(item["letter_details"] != None):item["letter_details"]='<div style="font-family:Helvetica Neue,sans-serif;font-size: 12px !important;">'+item["letter_details"]+"</div>"


    return item

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
    file_path = os.path.join(base_path, 'quote_format_final.JSON')
    with open(file_path, 'r') as f:
        setting_json = json.load(f)
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
        self.leftValue = left["value"] or "N/A"
        self.rightValue = right["value"] or "N/A"

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

    models = populate_cart_item_model(quote_id)
    # print(models)
    for cart_model in models:
        product_code = get_key(cart_model, 'cartProductCode')
        product_key = get_key(cart_model, 'cartProductCode')
        sub_category = get_key(cart_model, 'subcategory')
        root_key = f"{product_code}-{sub_category}"
        if(product_code =='VCDR' and 'operator' in cart_model and cart_model['operator']['value'] == 'Motorized' ) : product_key = product_key+'-ACT'
        if(product_code =='VCDA' and 'damperOperator' in cart_model and cart_model['damperOperator']['value'] == 'Motorized' ) : product_key = product_key+'-ACT'

        if root_key not in keys:
            prefix = get_prefix(str(len(keys)))
            keys[root_key] = f"{prefix}{root_key}"
            output[keys[root_key]] = ProductRootNode(sub_category, product_code).__dict__

        prd_root_node = output[keys[root_key]]
        model_group_node = prd_root_node.get('items')
        group_key = get_key(cart_model, product_family_map[product_key]['headerKey'])

        if group_key not in child_keys:
            prefix = get_prefix(str(len(child_keys)))
            child_keys[group_key] = f"{prefix}{group_key}"
            c_node = ChildNode().__dict__
            c_node["modelName"] = get_key(cart_model, 'modelDescription')
            c_node["subcategory"] = get_key(cart_model, 'subcategory')
            c_node["headers"] = populate_header_values(cart_model, product_family_map[product_key]['header'])
            c_node["headersDisplay"] = populate_header_display(c_node.get("headers"))
            c_node["details"] = []
            c_node["summary"] = {}
            model_group_node[child_keys[group_key]] = c_node

        model_group_node[child_keys[group_key]]["details"].append(
            populate_detail(cart_model, product_family_map[product_key]['detail'])
        )
        model_group_node[child_keys[group_key]]["summary"] = populate_summary(
            cart_model,
            product_family_map[product_key]['summary'],
            model_group_node[child_keys[group_key]]["summary"]
        )
        prdTotal =  Decimal(re.sub(r'[^\d.]', '', str(prd_root_node["productTotal"]))) + Decimal(get_decimal(get_key(cart_model, 'cartAmount')))
       
        print("check ",get_decimal(get_key(cart_model, 'cartAmount')))
        print("check prdTotal ",prdTotal)

        prd_root_node["productTotal"] = f"{prdTotal:,.2f}"
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
            summ[k] = Decimal(re.sub(r'[^\d.]', '', summ.get(k, str(0)))) + get_decimal(features[k]["value"])
            if(k=='qty') : summ[k] = f"{summ[k]:,.0f}"
            else :
                summ[k] = f"{summ[k]:,.2f}"
    print('summ',summ)
    return summ
def populate_value( features, formula: str) -> Union[str, Decimal]:
    if not formula.startswith("CONCAT"):
            # print('formula :',formula)
            if(formula =='specification' and 'productCategory' in features) :
                if('120' in features['productCategory']['value']) : return 'Fire Rated - 120 Min'
                if('240' in features['productCategory']['value']) : return 'Fire Rated - 240 Min'
                return 'Normal'
            if(formula =='linkTemperature' and 'storOrDtorOption' in features) :
                if(features['storOrDtorOption']['value']=='NA') : return 'NA'
            if((formula =='sleeveThickness' and 'sleeveThickness' in features) or (formula =='frameThickness' and 'frameThickness' in features)) :
                res = features[formula]['value']
                if(res !=0) : return  f"{res:,.1f}"
            if(formula in features): return features[formula]['value']
            return ''
    keys = exec(formula)
    print('keys - ',keys)
    return "".join([features.get(k, {}).get("value", "") if "string" not in k else k.replace("string", "") for k in keys])

# def populate_value( features, formula: str) -> Union[str, Decimal]:
#     if not formula.startswith("CONCAT"):
#         return features.get(formula, {}).get("value", "")
#     keys = exec(formula)
#     return "".join([features.get(k, {}).get("value", "") if "string" not in k else k.replace("string", "") for k in keys])

def exec( formula) -> List[str]:
    match = re.search(r'CONCAT\((.*?)\)', formula)
    if match:
        return match.group(1).split(',')
    return []