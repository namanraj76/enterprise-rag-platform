import json
import httpx


def main():
    payload = {"question": "How do I fix AUTH-401 after a gateway upgrade?", "top_k": 3}
    with httpx.Client(timeout=10.0) as client:
        resp = client.post("http://127.0.0.1:8000/query", json=payload)
        resp.raise_for_status()
        print(json.dumps(resp.json(), indent=2))


if __name__ == "__main__":
    main()
