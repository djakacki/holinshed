#!/usr/bin/env python3
"""
run_pipeline.py — Full Holinshed NER + Authority List pipeline.

STEPS:
  1. Extract & clean items from TEI XML         -> items_clean.json
  2. LLM NER tagging (persons & places)         -> items_ner.json
  3. Write <persName>/<placeName> back to XML   -> Holinshed_vol4_tagged.xml
  4. Build per-file frequency lists             -> persons_list.csv, places_list.csv
  5. Merge multi-file NER corpus                -> corpus_names.json, corpus_counts.json
  6. Fuzzy-cluster spelling variants            -> clusters.json
  7. LLM normalization + authority list draft   -> authority_list_draft.csv

USAGE:
  export ANTHROPIC_API_KEY="sk-ant-..."
  python3 run_pipeline.py              # full run
  python3 run_pipeline.py --sample 300 # test on 300 items
  python3 run_pipeline.py --resume --from-step 2   # resume interrupted NER
  python3 run_pipeline.py --from-step 5            # authority list only

  To add a second volume: edit NER_FILES in step5_merge.py, then:
  python3 run_pipeline.py --from-step 5
"""

import argparse, json, os, subprocess, sys
from pathlib import Path

WORK_DIR = Path(__file__).parent

SCRIPTS = {
    1: WORK_DIR / "step1_extract.py",
    2: WORK_DIR / "step2_ner.py",
    3: WORK_DIR / "step3_writeback.py",
    4: WORK_DIR / "step4_lists.py",
    5: WORK_DIR / "step5_merge.py",
    6: WORK_DIR / "step6_cluster.py",
    7: WORK_DIR / "step7_normalize.py",
}

STEP_NAMES = {
    1: "Extract & clean items from TEI XML",
    2: "LLM NER tagging",
    3: "Write tags back to TEI XML",
    4: "Build per-file name frequency lists",
    5: "Merge multi-file NER corpus",
    6: "Fuzzy-cluster spelling variants",
    7: "LLM normalization + authority list",
}

def run(script):
    result = subprocess.run([sys.executable, str(script)], env=os.environ.copy())
    if result.returncode != 0:
        sys.exit(f"Script failed: {Path(script).name}")

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--sample",    type=int, default=0)
    parser.add_argument("--resume",    action="store_true")
    parser.add_argument("--from-step", type=int, default=1)
    parser.add_argument("--to-step",   type=int, default=7)
    args = parser.parse_args()

    if not os.environ.get("ANTHROPIC_API_KEY"):
        sys.exit("ERROR: Set ANTHROPIC_API_KEY environment variable.")

    for step in range(args.from_step, args.to_step + 1):
        print(f"\n{'='*50}\nSTEP {step}: {STEP_NAMES[step]}\n{'='*50}")
        if step == 1 and not args.resume:
            run(SCRIPTS[1])
            if args.sample:
                items = json.load(open(WORK_DIR / "items_clean.json"))
                json.dump(items[:args.sample], open(WORK_DIR / "items_clean.json","w"),
                          ensure_ascii=False, indent=2)
                print(f"(sample: {args.sample} items)")
        elif step == 2:
            if not args.resume:
                (WORK_DIR / "ner_progress.json").unlink(missing_ok=True)
            run(SCRIPTS[2])
        elif step == 7:
            if not args.resume:
                (WORK_DIR / "norm_progress.json").unlink(missing_ok=True)
            run(SCRIPTS[7])
        else:
            run(SCRIPTS[step])

    print("\nDone. Outputs:")
    for f in ["Holinshed_vol4_tagged.xml","persons_list.csv","places_list.csv",
              "authority_list_draft.csv","ner_summary_report.txt"]:
        print(f"  outputs/{f}")

if __name__ == "__main__":
    main()
