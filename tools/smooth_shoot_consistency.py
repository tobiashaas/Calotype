"""Temporal and burst consistency smoother for Calotype developed shoots."""

import re
import shutil
from pathlib import Path

def parse_xmp(content: str) -> dict:
    data = {}
    m_temp = re.search(r'crs:Temperature="(\d+)"', content)
    if m_temp:
        data["temp"] = int(m_temp.group(1))
    m_tint = re.search(r'crs:Tint="(-?\d+)"', content)
    if m_tint:
        data["tint"] = int(m_tint.group(1))
    m_exp = re.search(r'crs:Exposure2012="(-?[\d.]+)"', content)
    if m_exp:
        data["exposure"] = float(m_exp.group(1))
    return data

def update_xmp(content: str, temp: int, tint: int, exp: float) -> str:
    content = re.sub(r'crs:Temperature="\d+"', f'crs:Temperature="{temp}"', content)
    content = re.sub(r'crs:Tint="-?\d+"', f'crs:Tint="{tint}"', content)
    content = re.sub(r'crs:Exposure2012="-?[\d.]+"', f'crs:Exposure2012="{exp:.2f}"', content)
    return content

def smooth_series(records: list[dict], window_size: int = 5, temp_jump_thresh: int = 250, exp_jump_thresh: float = 0.35):
    """Applies outlier-resistant smoothing across consecutive frames.
    
    Preserves real scene transitions (large continuous shifts), but removes 
    isolated 1-frame or 2-frame wobbles (e.g. 5500K -> 6040K -> 5500K).
    """
    n = len(records)
    smoothed = [dict(r) for r in records]
    
    fixes_temp = 0
    fixes_exp = 0
    
    for i in range(n):
        # 1-frame isolated spike detection:
        if 0 < i < n - 1:
            prev_t = records[i - 1]["temp"]
            curr_t = records[i]["temp"]
            next_t = records[i + 1]["temp"]
            
            # If prev and next are close to each other, but curr is jumping:
            if abs(prev_t - next_t) < 100 and abs(curr_t - prev_t) >= temp_jump_thresh:
                target_t = int(round((prev_t + next_t) / 2))
                smoothed[i]["temp"] = target_t
                fixes_temp += 1
                
            prev_e = records[i - 1]["exp"]
            curr_e = records[i]["exp"]
            next_e = records[i + 1]["exp"]
            if abs(prev_e - next_e) < 0.15 and abs(curr_e - prev_e) >= exp_jump_thresh:
                target_e = round((prev_e + next_e) / 2, 2)
                smoothed[i]["exp"] = target_e
                fixes_exp += 1
                
        # 2-frame wobble detection: prev, curr, curr+1 (wobbled together), next
        if 0 < i < n - 2:
            prev_t = records[i - 1]["temp"]
            c1_t = records[i]["temp"]
            c2_t = records[i + 1]["temp"]
            next_t = records[i + 2]["temp"]
            if abs(prev_t - next_t) < 120 and abs(c1_t - c2_t) < 80 and abs(c1_t - prev_t) >= temp_jump_thresh:
                target_t = int(round((prev_t + next_t) / 2))
                smoothed[i]["temp"] = target_t
                smoothed[i + 1]["temp"] = target_t
                fixes_temp += 2
                
    return smoothed, fixes_temp, fixes_exp

def main():
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--dir", default=r"E:\Marryween")
    parser.add_argument("--pattern", default="DP3A*.xmp")
    parser.add_argument("--apply", action="store_true", help="Write changes to XMP files")
    args = parser.parse_args()
    
    folder = Path(args.dir)
    xmp_files = sorted(folder.glob(args.pattern))
    print(f"Loaded {len(xmp_files)} XMPs from {folder}")
    
    records = []
    for xmp in xmp_files:
        c = xmp.read_text(encoding="utf-8", errors="ignore")
        v = parse_xmp(c)
        records.append({
            "path": xmp,
            "temp": v.get("temp", 5500),
            "tint": v.get("tint", 10),
            "exp": v.get("exposure", 0.0),
            "raw_content": c,
        })
        
    smoothed, fix_temp, fix_exp = smooth_series(records)
    print(f"\nConsistency Analysis Results:")
    print(f"  Detected & Smoothed Temperature Wobbles: {fix_temp} frames")
    print(f"  Detected & Smoothed Exposure Spikes:     {fix_exp} frames")
    
    # Calculate deltas before and after
    def get_deltas(recs):
        td = [abs(recs[i]["temp"] - recs[i-1]["temp"]) for i in range(1, len(recs))]
        ed = [abs(recs[i]["exp"] - recs[i-1]["exp"]) for i in range(1, len(recs))]
        return td, ed
        
    orig_td, orig_ed = get_deltas(records)
    smooth_td, smooth_ed = get_deltas(smoothed)
    
    print(f"\nBefore smoothing:")
    print(f"  Max Temp Delta: {max(orig_td)} K | Avg: {sum(orig_td)/len(orig_td):.1f} K | Jumps >300K: {sum(1 for d in orig_td if d > 300)}")
    print(f"  Max Exp Delta:  {max(orig_ed):.2f} EV | Avg: {sum(orig_ed)/len(orig_ed):.2f} EV | Jumps >0.5EV: {sum(1 for d in orig_ed if d > 0.5)}")
    
    print(f"\nAfter smoothing:")
    print(f"  Max Temp Delta: {max(smooth_td)} K | Avg: {sum(smooth_td)/len(smooth_td):.1f} K | Jumps >300K: {sum(1 for d in smooth_td if d > 300)}")
    print(f"  Max Exp Delta:  {max(smooth_ed):.2f} EV | Avg: {sum(smooth_ed)/len(smooth_ed):.2f} EV | Jumps >0.5EV: {sum(1 for d in smooth_ed if d > 0.5)}")
    
    if args.apply:
        print(f"\nApplying smoothed values to {len(smoothed)} XMP sidecars...")
        modified = 0
        for orig, sm in zip(records, smoothed):
            if orig["temp"] != sm["temp"] or orig["exp"] != sm["exp"]:
                new_c = update_xmp(orig["raw_content"], sm["temp"], sm["tint"], sm["exp"])
                orig["path"].write_text(new_c, encoding="utf-8")
                modified += 1
        print(f"Successfully updated {modified} XMP files.")
    else:
        print("\nDry-run completed. Run with --apply to write changes.")

if __name__ == "__main__":
    main()
