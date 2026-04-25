#!/usr/bin/env python3
"""
Current Time Tool - Fetches real-time from TimeAPI.io

Provides accurate current time for any timezone.
Used by router for time_query classification.
"""

from __future__ import annotations

import json
import sys
import urllib.request
import urllib.error
from datetime import datetime
from pathlib import Path


def get_current_time(timezone: str = "UTC") -> dict:
    """
    Fetch current time from TimeAPI.io.
    
    Args:
        timezone: Timezone string (e.g., "Australia/Melbourne", "America/New_York")
    
    Returns:
        Dict with time data or error
    """
    # Handle common city and country aliases
    timezone_aliases = {
        # Australia / Pacific
        "melbourne": "Australia/Melbourne",
        "sydney": "Australia/Sydney",
        "brisbane": "Australia/Brisbane",
        "perth": "Australia/Perth",
        "adelaide": "Australia/Adelaide",
        "auckland": "Pacific/Auckland",
        "wellington": "Pacific/Auckland",
        "fiji": "Pacific/Fiji",
        "honolulu": "Pacific/Honolulu",
        "hawaii": "Pacific/Honolulu",
        
        # Asia
        "tokyo": "Asia/Tokyo",
        "japan": "Asia/Tokyo",
        "beijing": "Asia/Shanghai",
        "china": "Asia/Shanghai",
        "shanghai": "Asia/Shanghai",
        "hong kong": "Asia/Hong_Kong",
        "singapore": "Asia/Singapore",
        "bangkok": "Asia/Bangkok",
        "thailand": "Asia/Bangkok",
        "seoul": "Asia/Seoul",
        "korea": "Asia/Seoul",
        "taipei": "Asia/Taipei",
        "taiwan": "Asia/Taipei",
        "mumbai": "Asia/Kolkata",
        "india": "Asia/Kolkata",
        "delhi": "Asia/Kolkata",
        "dubai": "Asia/Dubai",
        "uae": "Asia/Dubai",
        "jordan": "Asia/Amman",
        "amman": "Asia/Amman",
        "israel": "Asia/Jerusalem",
        "jerusalem": "Asia/Jerusalem",
        "tel aviv": "Asia/Jerusalem",
        "saudi arabia": "Asia/Riyadh",
        "riyadh": "Asia/Riyadh",
        "turkey": "Europe/Istanbul",
        "istanbul": "Europe/Istanbul",
        "pakistan": "Asia/Karachi",
        "karachi": "Asia/Karachi",
        "indonesia": "Asia/Jakarta",
        "jakarta": "Asia/Jakarta",
        "malaysia": "Asia/Kuala_Lumpur",
        "kuala lumpur": "Asia/Kuala_Lumpur",
        "philippines": "Asia/Manila",
        "manila": "Asia/Manila",
        "vietnam": "Asia/Ho_Chi_Minh",
        "ho chi minh": "Asia/Ho_Chi_Minh",
        "hanoi": "Asia/Ho_Chi_Minh",
        "bangladesh": "Asia/Dhaka",
        "dhaka": "Asia/Dhaka",
        "nepal": "Asia/Kathmandu",
        "kathmandu": "Asia/Kathmandu",
        "sri lanka": "Asia/Colombo",
        "colombo": "Asia/Colombo",
        "myanmar": "Asia/Yangon",
        "yangon": "Asia/Yangon",
        
        # Europe
        "london": "Europe/London",
        "uk": "Europe/London",
        "england": "Europe/London",
        "paris": "Europe/Paris",
        "france": "Europe/Paris",
        "berlin": "Europe/Berlin",
        "germany": "Europe/Berlin",
        "moscow": "Europe/Moscow",
        "russia": "Europe/Moscow",
        "rome": "Europe/Rome",
        "italy": "Europe/Rome",
        "madrid": "Europe/Madrid",
        "spain": "Europe/Madrid",
        "barcelona": "Europe/Madrid",
        "amsterdam": "Europe/Amsterdam",
        "netherlands": "Europe/Amsterdam",
        "brussels": "Europe/Brussels",
        "belgium": "Europe/Brussels",
        "zurich": "Europe/Zurich",
        "switzerland": "Europe/Zurich",
        "vienna": "Europe/Vienna",
        "austria": "Europe/Vienna",
        "stockholm": "Europe/Stockholm",
        "sweden": "Europe/Stockholm",
        "oslo": "Europe/Oslo",
        "norway": "Europe/Oslo",
        "copenhagen": "Europe/Copenhagen",
        "denmark": "Europe/Copenhagen",
        "helsinki": "Europe/Helsinki",
        "finland": "Europe/Helsinki",
        "warsaw": "Europe/Warsaw",
        "poland": "Europe/Warsaw",
        "athens": "Europe/Athens",
        "greece": "Europe/Athens",
        "lisbon": "Europe/Lisbon",
        "portugal": "Europe/Lisbon",
        "dublin": "Europe/Dublin",
        "ireland": "Europe/Dublin",
        "prague": "Europe/Prague",
        "czech republic": "Europe/Prague",
        "budapest": "Europe/Budapest",
        "hungary": "Europe/Budapest",
        "bucharest": "Europe/Bucharest",
        "romania": "Europe/Bucharest",
        "sofia": "Europe/Sofia",
        "bulgaria": "Europe/Sofia",
        "belgrade": "Europe/Belgrade",
        "serbia": "Europe/Belgrade",
        "zagreb": "Europe/Zagreb",
        "croatia": "Europe/Zagreb",
        "ukraine": "Europe/Kiev",
        "kiev": "Europe/Kiev",
        "kyiv": "Europe/Kiev",
        
        # Middle East / Africa
        "cairo": "Africa/Cairo",
        "egypt": "Africa/Cairo",
        "johannesburg": "Africa/Johannesburg",
        "south africa": "Africa/Johannesburg",
        "cape town": "Africa/Johannesburg",
        "nairobi": "Africa/Nairobi",
        "kenya": "Africa/Nairobi",
        "lagos": "Africa/Lagos",
        "nigeria": "Africa/Lagos",
        "casablanca": "Africa/Casablanca",
        "morocco": "Africa/Casablanca",
        "tunis": "Africa/Tunis",
        "tunisia": "Africa/Tunis",
        "algiers": "Africa/Algiers",
        "algeria": "Africa/Algiers",
        "tripoli": "Africa/Tripoli",
        "libya": "Africa/Tripoli",
        "khartoum": "Africa/Khartoum",
        "sudan": "Africa/Khartoum",
        "addis ababa": "Africa/Addis_Ababa",
        "ethiopia": "Africa/Addis_Ababa",
        "accra": "Africa/Accra",
        "ghana": "Africa/Accra",
        "dakar": "Africa/Dakar",
        "senegal": "Africa/Dakar",
        "botswana": "Africa/Gaborone",
        "gaborone": "Africa/Gaborone",
        "zimbabwe": "Africa/Harare",
        "harare": "Africa/Harare",
        "zambia": "Africa/Lusaka",
        "lusaka": "Africa/Lusaka",
        "malawi": "Africa/Blantyre",
        "blantyre": "Africa/Blantyre",
        "tanzania": "Africa/Dar_es_Salaam",
        "dar es salaam": "Africa/Dar_es_Salaam",
        "uganda": "Africa/Kampala",
        "kampala": "Africa/Kampala",
        "rwanda": "Africa/Kigali",
        "kigali": "Africa/Kigali",
        "burundi": "Africa/Bujumbura",
        "bujumbura": "Africa/Bujumbura",
        "madagascar": "Indian/Antananarivo",
        "antananarivo": "Indian/Antananarivo",
        "mauritius": "Indian/Mauritius",
        "port louis": "Indian/Mauritius",
        "seychelles": "Indian/Mahe",
        " victoria": "Indian/Mahe",
        "namibia": "Africa/Windhoek",
        "windhoek": "Africa/Windhoek",
        "angola": "Africa/Luanda",
        "luanda": "Africa/Luanda",
        "mozambique": "Africa/Maputo",
        "maputo": "Africa/Maputo",
        "democratic republic of congo": "Africa/Kinshasa",
        "congo": "Africa/Kinshasa",
        "kinshasa": "Africa/Kinshasa",
        "gabon": "Africa/Libreville",
        "libreville": "Africa/Libreville",
        "cameroon": "Africa/Douala",
        "douala": "Africa/Douala",
        "ivory coast": "Africa/Abidjan",
        "cote divoire": "Africa/Abidjan",
        "abidjan": "Africa/Abidjan",
        "guinea": "Africa/Conakry",
        "conakry": "Africa/Conakry",
        "sierra leone": "Africa/Freetown",
        "freetown": "Africa/Freetown",
        "liberia": "Africa/Monrovia",
        "monrovia": "Africa/Monrovia",
        "mali": "Africa/Bamako",
        "bamako": "Africa/Bamako",
        "burkina faso": "Africa/Ouagadougou",
        "ouagadougou": "Africa/Ouagadougou",
        "niger": "Africa/Niamey",
        "niamey": "Africa/Niamey",
        "chad": "Africa/Ndjamena",
        "ndjamena": "Africa/Ndjamena",
        "central african republic": "Africa/Bangui",
        "bangui": "Africa/Bangui",
        "eritrea": "Africa/Asmara",
        "asmara": "Africa/Asmara",
        "djibouti": "Africa/Djibouti",
        "somalia": "Africa/Mogadishu",
        "mogadishu": "Africa/Mogadishu",
        "zanzibar": "Africa/Dar_es_Salaam",
        
        # Americas
        "new york": "America/New_York",
        "nyc": "America/New_York",
        "usa": "America/New_York",
        "us": "America/New_York",
        "united states": "America/New_York",
        "los angeles": "America/Los_Angeles",
        "la": "America/Los_Angeles",
        "california": "America/Los_Angeles",
        "chicago": "America/Chicago",
        "illinois": "America/Chicago",
        "denver": "America/Denver",
        "colorado": "America/Denver",
        "phoenix": "America/Phoenix",
        "arizona": "America/Phoenix",
        "seattle": "America/Los_Angeles",
        "washington": "America/New_York",
        "dc": "America/New_York",
        "boston": "America/New_York",
        "miami": "America/New_York",
        "atlanta": "America/New_York",
        "dallas": "America/Chicago",
        "texas": "America/Chicago",
        "houston": "America/Chicago",
        "san francisco": "America/Los_Angeles",
        "sf": "America/Los_Angeles",
        "las vegas": "America/Los_Angeles",
        "toronto": "America/Toronto",
        "canada": "America/Toronto",
        "vancouver": "America/Vancouver",
        "montreal": "America/Toronto",
        "mexico city": "America/Mexico_City",
        "mexico": "America/Mexico_City",
        "rio": "America/Sao_Paulo",
        "rio de janeiro": "America/Sao_Paulo",
        "sao paulo": "America/Sao_Paulo",
        "brazil": "America/Sao_Paulo",
        "brasilia": "America/Sao_Paulo",
        "buenos aires": "America/Argentina/Buenos_Aires",
        "argentina": "America/Argentina/Buenos_Aires",
        "santiago": "America/Santiago",
        "chile": "America/Santiago",
        "lima": "America/Lima",
        "peru": "America/Lima",
        "bogota": "America/Bogota",
        "colombia": "America/Bogota",
        "caracas": "America/Caracas",
        "venezuela": "America/Caracas",
        "quito": "America/Guayaquil",
        "ecuador": "America/Guayaquil",
    }
    
    # Normalize timezone
    tz_lower = timezone.lower().strip()
    if tz_lower in timezone_aliases:
        timezone = timezone_aliases[tz_lower]
    
    # Ensure proper format (replace spaces with underscores)
    timezone = timezone.replace(" ", "_")
    
    url = f"https://timeapi.io/api/Time/current/zone?timeZone={timezone}"
    
    try:
        req = urllib.request.Request(
            url,
            headers={
                "User-Agent": "LocalLucy/1.0 (Time Query Tool)",
                "Accept": "application/json",
            }
        )
        
        with urllib.request.urlopen(req, timeout=10) as response:
            data = json.loads(response.read().decode("utf-8"))
            
            return {
                "ok": True,
                "timezone": data.get("timeZone"),
                "datetime": data.get("dateTime"),
                "day_of_week": data.get("dayOfWeek"),
                "abbreviation": data.get("timeZone", "").split("/")[-1] if "/" in data.get("timeZone", "") else data.get("timeZone"),
                "dst": data.get("dstActive"),
                "year": data.get("year"),
                "month": data.get("month"),
                "day": data.get("day"),
                "hour": data.get("hour"),
                "minute": data.get("minute"),
                "time": data.get("time"),
                "date": data.get("date"),
            }
            
    except urllib.error.HTTPError as e:
        return {
            "ok": False,
            "error": f"HTTP {e.code}: {e.reason}",
            "help": "Use format like 'Australia/Melbourne' or 'America/New_York'",
        }
    except urllib.error.URLError as e:
        return {
            "ok": False,
            "error": f"Network error: {e.reason}",
        }
    except Exception as e:
        return {
            "ok": False,
            "error": str(e),
        }


def format_time_response(data: dict, query_location: str = "") -> str:
    """Format time API response into readable text."""
    if not data.get("ok"):
        return f"Error fetching time: {data.get('error', 'Unknown error')}"
    
    try:
        time_str = data.get("time", "?")
        date_str = data.get("date", "?")
        timezone = data.get("timezone", query_location or "Unknown")
        day = data.get("day_of_week", "")
        dst = data.get("dst", False)
        
        # Format time nicely (e.g., "2:53 PM" from "14:53")
        try:
            hour = int(data.get("hour", 0))
            minute = int(data.get("minute", 0))
            ampm = "AM" if hour < 12 else "PM"
            hour_12 = hour if hour <= 12 else hour - 12
            if hour_12 == 0:
                hour_12 = 12
            time_formatted = f"{hour_12}:{minute:02d} {ampm}"
        except:
            time_formatted = time_str
        
        lines = [
            f"The current time in {timezone} is {time_formatted}.",
            f"Date: {day}, {date_str}",
        ]
        
        if dst:
            lines.append("Daylight Saving Time is currently active.")
        
        return "\n".join(lines)
        
    except Exception as e:
        return f"Current time in {query_location or 'requested location'}: {data.get('time', 'unknown')}"


def main():
    """CLI interface."""
    if len(sys.argv) < 2:
        print("Usage: current_time_tool.py <timezone> [--format]", file=sys.stderr)
        print("Example: current_time_tool.py 'Australia/Melbourne' --format", file=sys.stderr)
        sys.exit(1)
    
    args = sys.argv[1:]
    format_output = "--format" in args
    if format_output:
        args.remove("--format")
    
    timezone = " ".join(args)
    result = get_current_time(timezone)
    
    if format_output:
        print(format_time_response(result, timezone))
    else:
        print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
