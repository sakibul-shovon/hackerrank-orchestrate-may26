"""Quick comparison of output vs expected sample tickets."""
import csv

# Load sample (expected)
with open("support_tickets/sample_support_tickets.csv", encoding="utf-8-sig") as f:
    reader = csv.DictReader(f)
    reader.fieldnames = [n.lower().strip() for n in reader.fieldnames]
    expected = list(reader)

# Load our output
with open("support_tickets/sample_output.csv", encoding="utf-8") as f:
    actual = list(csv.DictReader(f))

print(f"Expected: {len(expected)} | Actual: {len(actual)} tickets\n")

status_ok = 0
type_ok = 0
for i, (exp, act) in enumerate(zip(expected, actual)):
    s_match = "OK" if act.get("status","").lower() == exp.get("status","").lower() else "MISS"
    t_match = "OK" if act.get("request_type","").lower() == exp.get("request type","").lower() else "MISS"
    if s_match == "OK": status_ok += 1
    if t_match == "OK": type_ok += 1
    print(f"  Ticket {i+1}: status={act.get('status',''):>10} (exp={exp.get('status',''):>10}) [{s_match}]  type={act.get('request_type',''):>15} (exp={exp.get('request type',''):>15}) [{t_match}]  area={act.get('product_area','')}")

print(f"\nStatus accuracy:       {status_ok}/{len(expected)} = {status_ok/len(expected)*100:.0f}%")
print(f"Request type accuracy: {type_ok}/{len(expected)} = {type_ok/len(expected)*100:.0f}%")
