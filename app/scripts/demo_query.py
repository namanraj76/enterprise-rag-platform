import json
import httpx


def main():
    payload = {"message": "Hi! What can you help me with?"}
    with httpx.Client(timeout=10.0) as client:
        resp = client.post("http://127.0.0.1:8000/chat", json=payload)
        resp.raise_for_status()
        print(json.dumps(resp.json(), indent=2))


if __name__ == "__main__":
    main()
