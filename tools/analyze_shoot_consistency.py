"""Analyze temporal exposure and white-balance consistency in E:\\Marryween."""

import re
from pathlib import Path
from PIL import Image

MARRYWEEN_DIR = Path(r"E:\Marryween")

def get_exif_time(jpg_path: Path) -> str:
    try:
        with Image.open(jpg_path) as img:
            exif = img.getexif()
            # 306 = DateTime, 36867 = DateTimeOriginal
            return exif.get(36867) or exif.get(306) or ""
    except Exception:
        return ""

def parse_xmp(xmp_path: Path) -> dict:
    content = xmp_path.read_text(encoding="utf-8", errors="ignore")
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

def main():
    xmp_files = sorted(MARRYWEEN_DIR.glob("DP3A*.xmp"))
    print(f"Total XMPs found: {len(xmp_files)}")
    
    records = []
    for xmp in xmp_files:  # all 1837
        vals = parse_xmp(xmp)
        if vals:
            records.append({
                "file": xmp.stem,
                "temp": vals.get("temp", 0),
                "tint": vals.get("tint", 0),
                "exp": vals.get("exposure", 0.0),
            })
            
    print(f"Parsed {len(records)} records. Sample consecutive delta:")
    temp_deltas = []
    exp_deltas = []
    for i in range(1, len(records)):
        dt_temp = abs(records[i]["temp"] - records[i-1]["temp"])
        dt_exp = abs(records[i]["exp"] - records[i-1]["exp"])
        temp_deltas.append(dt_temp)
        exp_deltas.append(dt_exp)
        if dt_temp > 300 or dt_exp > 0.5:
            print(f"  Jump between {records[i-1]['file']} and {records[i]['file']}: "
                  f"ΔTemp={dt_temp}K ({records[i-1]['temp']} -> {records[i]['temp']}), "
                  f"ΔExp={dt_exp:+.2f} ({records[i-1]['exp']} -> {records[i]['exp']})")
                  
    if temp_deltas:
        print(f"\nStats over first 200 photos:")
        print(f"  Avg Temp Delta: {sum(temp_deltas)/len(temp_deltas):.1f} K (Max: {max(temp_deltas)} K)")
        print(f"  Avg Exp Delta:  {sum(exp_deltas)/len(exp_deltas):.2f} EV (Max: {max(exp_deltas):.2f} EV)")

if __name__ == "__main__":
    main()
