"""Scrape badatime.com tide data and output tide_data.json"""
import requests, json, re, sys, os
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

LOCATION_ID = 1443
URL = f"https://www.badatime.com/{LOCATION_ID}/tide"
KST = timezone(timedelta(hours=9))
OUTPUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "tide_data.json")

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
    "Accept-Language": "ko-KR,ko;q=0.9",
}

def parse_tide_table(soup):
    """Parse main tide table (table[1], 15 days)"""
    tables = soup.find_all("table")
    if len(tables) < 2:
        return []
    tide_table = tables[1]
    trs = tide_table.find_all("tr")
    rows = []

    for tr in trs:
        tds = tr.find_all("td")
        if not tds or "day-cell" not in str(tds[0].get("class", "")):
            continue

        try:
            day_cell = tds[0]
            date_text = day_cell.get_text(" ", strip=True)
            # Parse "14(일) 4.29"
            m = re.search(r'(\d+)\(\s*(\S+)\s*\)\s*([\d.]+)', date_text)

            moon_cell = tds[1] if len(tds) > 1 else None
            tide_cell = tds[2] if len(tds) > 2 else None
            flow_cell = tds[3] if len(tds) > 3 else None
            weather_cell = tds[4] if len(tds) > 4 else None
            manjo_cell = tds[5] if len(tds) > 5 else None
            ganjo_cell = tds[6] if len(tds) > 6 else None
            s_rs_cell = tds[7] if len(tds) > 7 else None
            m_rs_cell = tds[8] if len(tds) > 8 else None

            # Moon image
            moon_img = moon_cell.find("img") if moon_cell else None
            moon_src = moon_img.get("src", "") if moon_img else ""
            moon_num = re.search(r'/(\d+)\.png', moon_src)

            # Weather image
            w_img = weather_cell.find("img") if weather_cell else None
            weather_src = w_img.get("src", "") if w_img else ""

            # Tide class + flow
            tide_text = tide_cell.get_text(strip=True) if tide_cell else ""
            # Parse tide text: "5 물78%" / "8 물최대" / "조금" / "무시"
            tide_class = tide_text
            flow_val = None
            if tide_text:
                fm = re.search(r'(\d+)%', tide_text)
                if fm:
                    flow_val = int(fm.group(1))
                # Extract just the number part for tide class
                tm = re.match(r'(\d+|조금|무시)', tide_text)
                if tm:
                    tide_class = tm.group(1)

            # Manjo: "02:13 (628) ▲+555 14:17 (535) ▲+388"
            manjo_text = manjo_cell.get_text(" ", strip=True).replace("\xa0", " ") if manjo_cell else ""
            manjo_times = re.findall(r'(\d{2}:\d{2})\s*\(\s*(\d+)\s*\)\s*▲([+-]?\d+)', manjo_text)
            manjo = [{"time": t, "height": int(h), "diff": int(d)} for t, h, d in manjo_times]

            # Ganjo: "09:02 (147) ▼-481 20:58 ( 49) ▼-486" (NBSP issue)
            ganjo_text = ganjo_cell.get_text(" ", strip=True).replace("\xa0", " ") if ganjo_cell else ""
            ganjo_times = re.findall(r'(\d{2}:\d{2})\s*\(\s*(\d+)\s*\)\s*▼([+-]?\d+)', ganjo_text)
            ganjo = [{"time": t, "height": int(h), "diff": int(d)} for t, h, d in ganjo_times]

            # Sunrise/sunset
            s_rs = s_rs_cell.get_text(strip=True) if s_rs_cell else ""
            m_rs = m_rs_cell.get_text(strip=True) if m_rs_cell else ""

            row = {
                "day": int(m.group(1)) if m else None,
                "dow": m.group(2) if m else "",
                "lunar": m.group(3) if m else "",
                "tide_class": tide_class,
                "flow_pct": flow_val,
                "manjo": manjo,
                "ganjo": ganjo,
                "sunrise_set": s_rs,
                "moonrise_set": m_rs,
                "moon_img": int(moon_num.group(1)) if moon_num else None,
                "weather_img": weather_src,
            }
            # Determine month from context (first row has smaller day -> next month)
            if rows and row["day"] is not None and rows[-1]["day"] is not None:
                if row["day"] < rows[-1]["day"]:
                    row["month"] = rows[-1]["month"] + 1 if rows[-1]["month"] else 6
                else:
                    row["month"] = rows[-1]["month"] if rows[-1]["month"] else 6
            else:
                row["month"] = 6  # current month
            rows.append(row)
        except Exception as e:
            print(f"  Row parse error: {e}", file=sys.stderr)
            continue
    return rows


def parse_sea_weather(soup):
    """Parse sea weather forecast tables"""
    tables = soup.find_all("table")
    result = {"area": "", "daily": [], "extended": [], "hourly_labels": [], "hourly_data": {}}

    # Table 2: daily sea weather (바다날씨)
    if len(tables) > 2:
        trs = tables[2].find_all("tr")
        if trs:
            result["area"] = trs[0].get_text(strip=True)
        if len(trs) > 2:
            for tr in trs[2:]:
                tds = tr.find_all("td")
                texts = [td.get_text(strip=True) for td in tds]
                if not texts:
                    continue
                # Format: ["6.14(일)", "오전", "구름많음", "남동-남", "3-6", "0.5-1.0"]
                # or: ["오후", "구름많고소나기", "북-북동", "3-6", "0.5-0.5"]
                if "(" in texts[0] and ")" in texts[0]:
                    # New date row with am/pm
                    date_str = texts[0]
                    am_data = texts[1:] if len(texts) > 1 else []
                    result["daily"].append({"date": date_str, "times": []})
                    if len(am_data) >= 5:
                        result["daily"][-1]["times"].append({
                            "when": am_data[0], "weather": am_data[1],
                            "wind_dir": am_data[2], "wind_speed": am_data[3], "wave": am_data[4],
                        })
                elif texts[0] in ("오전", "오후"):
                    when = texts[0]
                    data = texts[1:]
                    if result["daily"] and len(data) >= 4:
                        result["daily"][-1]["times"].append({
                            "when": when, "weather": data[0],
                            "wind_dir": data[1], "wind_speed": data[2], "wave": data[3],
                        })

    # Table 3: extended forecast (5-day)
    if len(tables) > 3:
        trs = tables[3].find_all("tr")
        for tr in trs:
            tds = tr.find_all(["td", "th"])
            texts = [td.get_text(strip=True) for td in tds]
            if texts and texts[0] in ("날씨", "파고", "풍향", "풍속"):
                result["extended"].append(texts)

    # Table 4: hourly labels (the data is JS-loaded)
    if len(tables) > 4:
        trs = tables[4].find_all("tr")
        for tr in trs:
            tds = tr.find_all(["td", "th"])
            texts = [td.get_text(strip=True) for td in tds]
            if texts:
                key = texts[0]
                if key and len(texts) > 1:
                    result["hourly_labels"].append(key)

    return result


def parse_sea_temp(soup):
    """Parse sea temperature"""
    text = soup.get_text()
    patterns = [
        (r'(\d+\.\d+)℃', None),
        (r'수온\s*(\d+\.\d+)', None),
        (r'바다수온.*?(\d+\.\d+)', None),
    ]
    for pat, _ in patterns:
        m = re.search(pat, text)
        if m:
            return float(m.group(1))
    return None


def main():
    print(f"Scraping: {URL}")
    resp = requests.get(URL, headers=HEADERS, timeout=20)
    resp.encoding = "utf-8"
    soup = BeautifulSoup(resp.text, "lxml")

    tides = parse_tide_table(soup)
    sea_temp = parse_sea_temp(soup)
    sea_weather = parse_sea_weather(soup)

    now_kst = datetime.now(KST)
    data = {
        "location": "내파수도",
        "location_id": LOCATION_ID,
        "updated": now_kst.isoformat(),
        "sea_temp": sea_temp,
        "sea_weather": sea_weather,
        "tides": tides,
    }

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    today = now_kst.strftime("%m/%d")
    n_daily = len(sea_weather.get("daily", [])) if isinstance(sea_weather, dict) else 0
    print(f"Done! {len(tides)} days, sea temp={sea_temp}°C, weather={n_daily} days, updated={today}")
    for t in tides[:3]:
        mj = " ".join(f'{x["time"]}({x["height"]})' for x in t.get("manjo", []))
        print(f"  {t['month']}/{t['day']}({t['dow']}) lunar={t['lunar']} | {t['tide_class']} | flow={t['flow_pct']}% | manjo={mj}")


if __name__ == "__main__":
    main()
