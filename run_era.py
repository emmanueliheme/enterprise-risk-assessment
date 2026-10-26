"""Score the workbook from the command line and write the results to Excel.

    python run_era.py                       # sample bank
    python run_era.py --inputs my.xlsx --kri-overlay --out results.xlsx
"""
import argparse
from pathlib import Path

from era import ModelConfig, load_inputs, run
from era import reporting as rp
from era.data import DEFAULT_INPUTS

p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
p.add_argument("--inputs", default=DEFAULT_INPUTS)
p.add_argument("--out", default="outputs/era_results.xlsx")
p.add_argument("--kri-overlay", action="store_true")
p.add_argument("--weighted", action="store_true", help="average impact and velocity instead of taking the worst case")
a = p.parse_args()

inputs = load_inputs(a.inputs)
if not inputs.ok:
    raise SystemExit("Input errors:\n- " + "\n- ".join(inputs.errors))
agg = "weighted" if a.weighted else "max"
res = run(inputs, ModelConfig(kri_overlay=a.kri_overlay, impact_aggregation=agg, velocity_aggregation=agg))
e = res.enterprise
print(f"ERA {e['era']:.2f} ({e['level']}) | inherent {e['inherent']:.2f} | control effectiveness {e['control_eff']:.0%}")
print(rp.category_table(res)[["Category", "Weight", "Residual", "Level", "Share of ERA"]].round(2).to_string(index=False))
Path(a.out).parent.mkdir(parents=True, exist_ok=True)
Path(a.out).write_bytes(rp.export_excel(res))
print(f"Saved {a.out}")
