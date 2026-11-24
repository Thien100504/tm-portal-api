filepath = "app/modules/automation/router.py"
with open(filepath, encoding="utf-8") as f:
    content = f.read()

content = content.replace("'AutomationRule'", "AutomationRule")

with open(filepath, "w", encoding="utf-8") as f:
    f.write(content)
