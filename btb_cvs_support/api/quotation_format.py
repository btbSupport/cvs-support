
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
def provide( quote_name: str):
    models = populate_cart_item_model(quote_name)
    if(models == None): return None
    compInfo = get_company_info()
    output = {"ci": {
        "cartItem": populate_cart_detail(models),
        "companyInfo": compInfo
    },
    "qt": get_quote_details(quote_name,compInfo["currency"])
    }
    # print("result -", output)
    file_path = "../apps/btb_cvs_support/btb_cvs_support/document/templates/quotation_format_"+output["ci"]["companyInfo"]["code"]+".docx"
    # file_path = "../apps/btb_cvs_support/btb_cvs_support/document/templates/quotation_format_eg.docx"

    # generate("templates/quotation.docx", json.loads(json.dumps(output)), format="pdf")
    generate(file_path, output, format="pdf",doc_type="Quotation",doc_name=quote_name,file_name="Quote_"+quote_name+".pdf")
    # generate(file_path, output, format="original",doc_type="Quotation",doc_name=quote_name,file_name="QuotationFormat_"+quote_name+".docx")
    return output
    # return 'Success'

def get_quote_details( quote_name: str,currency : str) -> Dict:
    from frappe.utils import money_in_words
    sql = f""" select docstatus,customer_name,address_display,in_words,contact_display,contact_designation,contact_mobile,contact_email,subject,project,name,terms,quotation_term_details,letter_details,standard_tc_details,grand_total,total_taxes_and_charges,net_total,discount_amount,additional_discount_percentage,total  from `tabQuotation` tqi where name ='{quote_name}'
    """
    items = frappe.db.sql(sql, as_dict=1)
    item = items[0]
    item["water_mark"]=" "
    if(item["docstatus"] != 1): item["water_mark"]="DRAFT"
    item["in_words"] = money_in_words(item['grand_total'], currency)
    item["address_display"] = '<span style="font-family:Helvetica Neue,sans-serif;font-size: 12px !important;">'+item['address_display']+"</span>"
    item["contact_display"] = '<span style="font-family:Helvetica Neue,sans-serif;font-size: 12px !important;">'+item['contact_display']+"</span>"
    item["grand_total"]=f"{(item['grand_total']):,.2f}"
    item["total_taxes_and_charges"]=f"{item['total_taxes_and_charges']:,.2f}"
    item["net_total"]=f"{item['net_total']:,.2f}"
    item["discount_amount"]=f"{item['discount_amount']:,.2f}"
    item["additional_discount_percentage"]=f"{item['additional_discount_percentage']:,.2f}"
    item["total"]=f"{item['total']:,.2f}"
    if("quotation_term_details" in item) :
        if(item["quotation_term_details"] != None):item["quotation_term_details"]='<div style="font-family:Helvetica Neue,sans-serif;font-size: 12px !important;">'+item["quotation_term_details"]+"</div>"
    else : item["quotation_term_details"] = ""
    if("standard_tc_details" in item ) :
        if(item["standard_tc_details"] != None):item["standard_tc_details"]='<div style="font-family:Helvetica Neue,sans-serif;font-size: 12px !important;">'+item["standard_tc_details"]+"</div>"
    else : item["standard_tc_details"] = ""
    if("terms" in item ) :
        if( item["terms"] != None):item["terms"]='<div style="font-family:Helvetica Neue,sans-serif;font-size: 12px !important;">'+item["terms"]+"</div>"
    else : item["terms"] = ""
    if("letter_details" in item ) :
        if( item["letter_details"] != None):item["letter_details"]='<div style="font-family:Helvetica Neue,sans-serif;font-size: 12px !important;">'+item["letter_details"]+"</div>"
    else : item["letter_details"] = ""
    item["userName"]=frappe.get_user().doc.full_name
    return item

def get_company_info() -> Dict:
    sql = f""" select tc.name,default_currency ,email,t.code  from tabCompany tc  join tabCountry t on tc.country = t.name
    """
    items = frappe.db.sql(sql, as_dict=1)
    return {
        "Email": items[0].email,
        "currency": items[0].default_currency,
        "name": items[0].name,
        "code": items[0].code
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
def populate_cart_detail(models) -> Dict[str, 'ProductRootNode']:
    # print('inside populate cart')
    output = {}
    product_family_map = populate_product_family_map()
    keys = {}
    child_keys = {}
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
        prdTotalQty =  Decimal(re.sub(r'[^\d.]', '', str(prd_root_node["totalqty"]))) + Decimal(get_decimal(get_key(cart_model, 'cartQty')))

        prd_root_node["productTotal"] = f"{prdTotal:,.2f}"
        prd_root_node["totalqty"] = f"{prdTotalQty:,.2f}"
        prd_root_node["items"] = model_group_node
    return output

def populate_header_values( features, header_map):
    output = []
    for label, field in header_map.items():
        val = str(populate_value(features, field))
        if(val == '' or val == None or val == 'None'): val='N/A'
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
            summ[k] = f"{summ[k]:,.2f}"
    print('summ',summ)
    return summ
def populate_value( features, formula: str) -> Union[str, Decimal]:
    thicknessFields=['sleeveThickness','frameThickness','bladeThickness','doorThickness','transitionThickness','perfThickness','casingThickness','frameThicknessLookup','bladeThicknessLookup']
    if not formula.startswith("CONCAT"):
            # print('formula :',formula)
            if(formula =='specification' and 'productCategory' in features) :
                if('120' in features['productCategory']['value']) : return 'Fire Rated - 120 Min'
                if('240' in features['productCategory']['value']) : return 'Fire Rated - 240 Min'
                return 'Normal'
            if(formula =='linkTemperature' and 'storOrDtorOption' in features) :
                if(features['storOrDtorOption']['value']=='NA') : return 'N/A'
            if(formula =='transitionThickness' and 'transition' in features) :
                if(features['transition']['value']=='NA') : return 'N/A'
            if(formula =='bladeThicknessForQuotePrint' and 'bladeType' in features) :
                if(features['bladeType']['value']!='AF' or ('bladeThicknessForQuotePrint' in features and features['bladeThicknessForQuotePrint']['value'] == '')) :
                   return populateThickness(features['bladeThicknessLookup']['value'])
            if(formula =='sleeveThickness' and 'sleeveType' in features) :
                if(features['sleeveType']['value']=='Integral' and 'frameThickness' in features) :
                   return populateThickness(features['frameThickness']['value'])
            if(formula in thicknessFields and formula in features) :
                return populateThickness(features[formula]['value'])
                # res = Decimal(str(features[formula]['value']))
                # if(res !=0 and res != '' and res != None) : return  f"{res:,.2f}"+' mm'
                # else :'NA'
            if(formula in features): 
                if(features[formula]['value'] == 'None' or features[formula]['value'] == 'NA'): return 'N/A'
                return features[formula]['value']
            return 'N/A'
    keys = exec(formula)
    print('keys - ',keys)
    # return "".join([features.get(k, {}).get("value", "") if "string" not in k else k.replace("string", "") for k in keys])
    return "".join([populate_value( features, k) if "string" not in k else k.replace("string", "") for k in keys])
def populateThickness(val):
    res = Decimal(str(val))
    if(res !=0 and res != '' and res != None and res !='None') : return  f"{res:,.2f}"+' mm'
    else :'N/A'

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