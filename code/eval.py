import subprocess
import time
import os
import csv

CONFIGS = ["naive", "retrieval", "rules", "full"]

print("=== Running Ablation Study ===")
print("This will run the pipeline 4 times with different configurations.")
print("Results will be saved to support_tickets/output_<config>.csv\n")

results = {}

for cfg in CONFIGS:
    start = time.time()
    out_file = f"../support_tickets/output_{cfg}.csv"
    print(f"Running config: {cfg.upper()}...")
    
    # We must ensure we are in the code/ directory, but since eval.py will be run from code/, 
    # we should use paths relative to the current working directory.
    cmd = [
        "python", "main.py",
        "--input", "../support_tickets/sample_support_tickets.csv",
        "--output", out_file,
        "--config", cfg,
        "--data-dir", "../data"
    ]
    
    subprocess.run(cmd, capture_output=True, text=True)
    duration = time.time() - start
    print(f"  Finished in {duration:.1f}s")
    
    results[cfg] = {
        "file": out_file,
        "time": duration
    }

print("\n=== Ablation Study Complete ===")

# Now we compare each file
try:
    with open("../support_tickets/sample_support_tickets.csv", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [n.lower().strip() for n in reader.fieldnames]
        expected = list(reader)

    print("\n| Configuration | Status acc | Type acc | Wall time |")
    print("|--------------|-----------|----------|-----------|")

    for cfg in CONFIGS:
        out_file = results[cfg]["file"]
        duration = results[cfg]["time"]
        
        try:
            with open(out_file, encoding="utf-8") as f:
                actual = list(csv.DictReader(f))
                
            status_ok = 0
            type_ok = 0
            
            for exp, act in zip(expected, actual):
                s_match = act.get("status","").lower() == exp.get("status","").lower()
                t_match = act.get("request_type","").lower() == exp.get("request type","").lower()
                if s_match: status_ok += 1
                if t_match: type_ok += 1
                
            status_acc = status_ok / len(expected) * 100 if expected else 0
            type_acc = type_ok / len(expected) * 100 if expected else 0
            
            print(f"| {cfg:<12} | {status_acc:>9.0f}% | {type_acc:>7.0f}% | {duration:>8.1f}s |")
        except Exception as e:
            print(f"| {cfg:<12} | Error reading output |")

    print("\nCopy this table into your README.md ablation study section!")
except Exception as e:
    print(f"Could not load expected CSV for comparison: {e}")
