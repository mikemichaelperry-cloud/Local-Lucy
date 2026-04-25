import json
import sys

def main():
    if len(sys.argv) < 3:
        print("ERR: verify_sources.py MODE META1 [META2 ...]")
        return 2
    mode = sys.argv[1]
    metas = []
    for p in sys.argv[2:]:
        with open(p, "r", encoding="utf-8") as f:
            metas.append(json.load(f))

    domains = [m.get("domain") for m in metas]
    unique = sorted(set([d for d in domains if d]))

    if mode == "news":
        if len(unique) < 2:
            print("ERR: insufficient independent domains")
            return 3
    elif mode == "vendor_or_gov":
        if len(unique) < 1:
            print("ERR: no sources")
            return 4
    else:
        print("ERR: unknown mode")
        return 5

    print("OK")
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
