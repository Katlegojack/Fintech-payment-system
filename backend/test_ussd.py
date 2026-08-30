#!/usr/bin/env python3
from urllib.parse import urlencode
from urllib.request import Request, urlopen

URL = "http://127.0.0.1:8000/ussd"

def send(text):
    body = urlencode({
        "sessionId": "ATUid_stocklink_demo",
        "serviceCode": "*384*12345#",
        "phoneNumber": "+27710001001",
        "text": text,
    }).encode()
    req = Request(URL, data=body, headers={"Content-Type": "application/x-www-form-urlencoded"}, method="POST")
    with urlopen(req) as response:
        return response.read().decode()

for label, text in [
    ("Dial code", ""),
    ("Check balance", "1"),
    ("Open contribution", "2"),
    ("Confirm R500", "2*1"),
    ("History", "3"),
    ("Group status", "4"),
]:
    print(f"\n--- {label} | text={text!r} ---")
    print(send(text))
