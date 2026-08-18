"""Smoke check: real jurisdiction lookups against the ingested GBA wards."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

PLACES = [
    ("Vidhana Soudha", 12.9794, 77.5912),
    ("Whitefield (ITPL)", 12.9856, 77.7367),
    ("Yelahanka New Town", 13.1007, 77.5963),
    ("Jayanagar 4th Block", 12.9250, 77.5838),
    ("Rajajinagar", 12.9916, 77.5546),
    ("Electronic City", 12.8452, 77.6602),
    ("Mysuru (outside GBA)", 12.2958, 76.6394),
]

FIELDS = [
    "corporation",
    "ward_no",
    "ward_name",
    "ward_name_kn",
    "zone",
    "division",
    "sub_division",
    "assembly",
]


def main() -> None:
    for label, lat, lng in PLACES:
        r = client.get("/api/v1/jurisdiction", params={"lat": lat, "lng": lng})
        print(f"\n=== {label}  ({lat}, {lng}) ===")

        if r.status_code != 200:
            body = r.json()
            print(f"  {r.status_code} {body['title']}: {body['detail']}")
            continue

        data = r.json()
        if not data["found"]:
            print(f"  NOT FOUND: {data['data']['corporation']['reason']}")
            continue

        for key in FIELDS:
            f = data["data"][key]
            value = str(f["value"])[:32] if f["value"] is not None else "-"
            print(f"  {key:<14} {value:<34} {f['status']:<10} {f['colour']}")

        print("  -- requested but not held --")
        for key in ("district", "planning_authority", "population"):
            if key in data["data"]:
                f = data["data"][key]
                print(f"  {key:<14} {f['status']:<10} {f['colour']}  {f['reason'][:56]}")

        print(f"  overall confidence: {data['confidence']['overall']}")

    cat = client.get("/api/v1/map/layers").json()["data"]
    print("\n=== layer catalogue ===")
    for layer in cat:
        print(f"  {layer['id']:<14} {layer['tier']:<4} {layer['rendering']:<14} {layer['title']}")


if __name__ == "__main__":
    main()
