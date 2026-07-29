import argparse
import sys

import requests


BASE_URL = "https://rxnav.nlm.nih.gov/REST"


def fetch_json(path: str) -> dict:
    response = requests.get(f"{BASE_URL}{path}", timeout=20)
    response.raise_for_status()
    return response.json()


def get_rxnorm_name(rxcui: str) -> str:
    data = fetch_json(f"/rxcui/{rxcui}/properties.json")
    return data.get("properties", {}).get("name", "")


def get_properties(rxcui: str) -> dict:
    return fetch_json(f"/rxcui/{rxcui}/properties.json").get("properties", {})


def get_all_related(rxcui: str) -> list[dict]:
    data = fetch_json(f"/rxcui/{rxcui}/allrelated.json")
    return data.get("allRelatedGroup", {}).get("conceptGroup", [])


def get_ingredient_strength(rxcui: str) -> list[dict]:
    data = fetch_json(f"/rxcui/{rxcui}/allProperties.json?prop=attributes")
    return data.get("propConceptGroup", {}).get("propConcept", [])


def get_atc_classes(rxcui: str) -> list[dict]:
    data = fetch_json(f"/rxclass/class/byRxcui.json?rxcui={rxcui}&relaSource=ATC")
    return data.get("rxclassDrugInfoList", {}).get("rxclassDrugInfo", [])


def print_header(title: str) -> None:
    print(f"\n=== {title} ===")


def print_related_groups(groups: list[dict]) -> None:
    if not groups:
        print("No related concepts found")
        return

    for group in groups:
        tty = group.get("tty", "UNKNOWN")
        concepts = group.get("conceptProperties", [])
        if not concepts:
            continue

        print_header(f"Related Terms ({tty})")
        seen = set()
        for concept in concepts:
            name = concept.get("name")
            rcui = concept.get("rxcui")
            if not name:
                continue
            key = (name, rcui)
            if key in seen:
                continue
            seen.add(key)
            if rcui:
                print(f"- {name} [RxCUI: {rcui}]")
            else:
                print(f"- {name}")


def print_attributes(attributes: list[dict]) -> None:
    if not attributes:
        print("No attributes found")
        return

    print_header("Attributes")
    for attr in attributes:
        name = attr.get("propName")
        value = attr.get("propValue")
        if name and value:
            print(f"- {name}: {value}")


def print_atc_classes(class_rows: list[dict]) -> None:
    if not class_rows:
        print("No ATC classes found")
        return

    print_header("ATC Classes")
    seen = set()
    for row in class_rows:
        item = row.get("rxclassMinConceptItem", {})
        class_id = item.get("classId")
        class_name = item.get("className")
        if not class_id and not class_name:
            continue
        key = (class_id, class_name)
        if key in seen:
            continue
        seen.add(key)
        print(f"- {class_id}: {class_name}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Print comprehensive RxNorm details for a given RxCUI"
    )
    parser.add_argument("rxcui", nargs="?", default="860975", help="RxCUI value")
    args = parser.parse_args()

    try:
        name = get_rxnorm_name(args.rxcui)
        properties = get_properties(args.rxcui)
        related_groups = get_all_related(args.rxcui)
        attributes = get_ingredient_strength(args.rxcui)
        atc_classes = get_atc_classes(args.rxcui)
    except requests.RequestException as exc:
        print(f"API request failed: {exc}", file=sys.stderr)
        return 1

    if not name:
        print("No name found for this RxCUI")
        return 2

    print_header("Primary RxNorm Record")
    print(f"RxCUI: {args.rxcui}")
    print(f"Name: {properties.get('name', name)}")
    if properties.get("tty"):
        print(f"TTY: {properties.get('tty')}")
    if properties.get("synonym"):
        print(f"Synonym: {properties.get('synonym')}")

    print_related_groups(related_groups)
    print_attributes(attributes)
    print_atc_classes(atc_classes)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
