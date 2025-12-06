"""Manual end-to-end API flow against a locally running server.

Prerequisites:
 1. Server running locally on http://127.0.0.1:8000
 2. .env configured with FIREBASE_WEB_API_KEY and Firebase credentials
 3. OpenAI key present if you want real story generation (this may incur cost)

This script will:
  - Sign up a Firebase user via Identity Toolkit REST API (email + password)
  - Register app user (/auth/register) with first child
  - List children (/children)
  - Create a second child (/children POST)
  - Generate a story (/stories/generate)
  - Poll story status (/stories/{story_id}) until completed or timeout
  - Fetch story details (/stories/details/{story_id})
  - Delete story (/stories/delete/{story_id})

SAFE MODE:
 Set environment variable SKIP_STORY_GENERATION=1 to skip real generation (will still call generate endpoint, but immediately delete).

Usage:
  PYTHONPATH=./ python scripts/manual_flow.py
"""

from __future__ import annotations
import os, time, json, sys, textwrap
import urllib.request
import requests
from typing import Optional

BASE_URL = os.environ.get("API_BASE_URL", "http://127.0.0.1:8000")
WEB_API_KEY = os.environ.get("FIREBASE_WEB_API_KEY") or "AIzaSyB1zev9GZAHJ57Rzlao8PuzJbxxI-i_6D0"

EMAIL_PREFIX = os.environ.get("TEST_EMAIL_PREFIX", "manualflow")
PASSWORD = os.environ.get("TEST_USER_PASSWORD", "TestPass123!")
SKIP_STORY = os.environ.get("SKIP_STORY_GENERATION") == "1"

def banner(title: str):
    print(f"\n{'='*8} {title} {'='*8}")

def sign_up_firebase() -> dict:
    email = f"{EMAIL_PREFIX}+{os.urandom(4).hex()}@example.com"
    url = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={WEB_API_KEY}"
    payload = {"email": email, "password": PASSWORD, "returnSecureToken": True}
    data = json.dumps(payload).encode()
    req = urllib.request.Request(url, data, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req) as resp:
        parsed = json.loads(resp.read().decode())
    return {"email": email, "idToken": parsed["idToken"], "localId": parsed["localId"]}

def post(path: str, body: dict, token: Optional[str] = None) -> requests.Response:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.post(f"{BASE_URL}{path}", headers=headers, data=json.dumps(body))
    return resp

def get(path: str, token: Optional[str] = None, params: Optional[dict] = None) -> requests.Response:
    headers = {}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    resp = requests.get(f"{BASE_URL}{path}", headers=headers, params=params)
    return resp

def delete(path: str, token: Optional[str] = None, body: Optional[dict] = None) -> requests.Response:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    data = json.dumps(body or {})
    resp = requests.delete(f"{BASE_URL}{path}", headers=headers, data=data)
    return resp
def main():
    banner("Firebase SignUp")
    fb = sign_up_firebase()
    print("Email:", fb["email"])
    print("LocalID:", fb["localId"])
    print("ID Token (truncated):", fb["idToken"][:50] + "...")

    token = fb["idToken"]

    banner("Register /auth/register")
    reg_body = {
        "firebase_token": token,
        "parent": {"name": "Manual Tester", "email": fb["email"]},
        "child": {"name": "Ava", "age": 6, "gender": "female", "interests": ["reading", "adventure"]},
        "system_prompt": "Be concise and cheerful for Ava."
    }
    reg_resp = post("/auth/register", reg_body)
    print("Status:", reg_resp.status_code)
    print(reg_resp.text[:400])
    if reg_resp.status_code not in (200, 201):
        print(f"Registration failed (status {reg_resp.status_code}); exiting")
        sys.exit(1)
    reg_json = reg_resp.json()
    default_child = reg_json.get("default_child_id")
    user_id = reg_json.get("user_id")
    print("Default Child:", default_child)
    print("User ID:", user_id)

    banner("List Children /children")
    children_resp = get("/children", token)
    print("Status:", children_resp.status_code)
    print(children_resp.text[:400])

    banner("Create Second Child")
    second_body = {
        "firebase_token": token,
        "name": "Liam",
        "age": 5,
        "gender": "male",
        "interests": ["space", "dinosaurs"]
    }
    second_resp = post("/children", second_body, token)
    print("Status:", second_resp.status_code)
    print(second_resp.text[:400])
    second_child_id = None
    if second_resp.ok:
        second_child_id = second_resp.json().get("child_id")
        print("Second Child ID:", second_child_id)

    banner("Generate Story (/stories/generate)")
    gen_body = {
        "firebase_token": token,
        "child_id": default_child,
        "prompt": "A short story about Ava exploring a friendly forest",
        "story_length": "short",
        "art_style": "watercolor"
    }
    gen_resp = post("/stories/generate", gen_body)
    print("Status:", gen_resp.status_code)
    print(gen_resp.text[:400])
    if not gen_resp.ok:
        print("Story generation failed; aborting further story steps")
        return
    gen_json = gen_resp.json()
    story_id = gen_json.get("story_id")
    print("Story ID:", story_id)

    if SKIP_STORY:
        print("SKIP_STORY_GENERATION=1 -> skipping polling; deleting immediately")
    else:
        banner("Poll Story Status")
        start = time.time()
        final_status = None
        while time.time() - start < 120:  # 2 minute timeout
            status_resp = get(f"/stories/{story_id}")
            if not status_resp.ok:
                print("Status check failed:", status_resp.status_code, status_resp.text[:200])
                time.sleep(3)
                continue
            st_json = status_resp.json()
            st = st_json.get("status")
            print(f"Status: {st}")
            if st in {"completed", "failed"}:
                final_status = st
                break
            time.sleep(4)
        print("Final Status:", final_status)
        if final_status == "completed":
            banner("Fetch Story Details")
            details_resp = get(f"/stories/details/{story_id}")
            print("Details status:", details_resp.status_code)
            print(details_resp.text[:400])
    
    banner("Delete Story")
    del_resp = delete(f"/stories/delete/{story_id}", body={"firebase_token": token})
    print("Delete status:", del_resp.status_code)
    print(del_resp.text[:400])

    banner("List User Stories")
    list_resp = get("/stories/user/stories", token, params={"limit": 5})
    print("List status:", list_resp.status_code)
    print(list_resp.text[:400])

    banner("Done")
    print("Flow complete")

if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("Interrupted")
    except Exception as e:
        print("Unhandled error:", e)
        raise
