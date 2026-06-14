"""Scrape badatime.com tide data and output tide_data.json"""
import requests, json, re, sys, os
from bs4 import BeautifulSoup
from datetime import datetime, timezone, timedelta

LOCATION_ID = 1442
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
    """Parse sea weather forecast (table[3] or table[2])"""
    tables = soup.find_all("table")
    forecasts = []
    for ti in [2, 3, 4, 5]:
        if ti >= len(tables):
            break
        table = tables[ti]
        trs = table.find_all("tr")
        for tr in trs:
            tds = tr.find_all(["td", "th"])
            text = " | ".join(td.get_text(strip=True) for td in tds if td.get_text(strip=True))
            if text and len(text) > 5:
                forecasts.append(text)
    return forecasts[:20]


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
        "location": "대길산도",
        "location_id": LOCATION_ID,
        "updated": now_kst.isoformat(),
        "sea_temp": sea_temp,
        "sea_weather": sea_weather[:10],
        "tides": tides,
    }

    with open(OUTPUT, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    today = now_kst.strftime("%m/%d")
    print(f"Done! {len(tides)} days, sea temp={sea_temp}°C, updated={today}")
    for t in tides[:3]:
        mj = " ".join(f'{x["time"]}({x["height"]})' for x in t.get("manjo", []))
        print(f"  {t['month']}/{t['day']}({t['dow']}) lunar={t['lunar']} | {t['tide_class']} | flow={t['flow_pct']}% | manjo={mj}")


if __name__ == "__main__":
    main()
