import requests
import json

def generate(template_path:str, datasource: dict, **kwargs):
    url = "https://onesign.digital/onedoc/convert"
    data = {
        "dataSource": json.dumps(datasource),
        "outputFormat": kwargs.get("format", "")
    }
    files = {
        "file": open(template_path, "rb")
    }
    response = requests.post(url, data = data, files = files)
    print(response.text)
    with open("templates/output.pdf", "wb") as f:
        f.write(response.content)
    
    
if(__name__ == "__main__"):
    generate("templates/quotation.docx", {"quote": {"name": "Test"}}, format="pdf")