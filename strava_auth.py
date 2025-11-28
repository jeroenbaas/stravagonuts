import http.server
import socketserver
import webbrowser
import json
import urllib.parse
import requests
import threading
import sys
import time
import os

SECRETS_FILE = "secrets.json"
STRAVA_AUTH_URL = "https://www.strava.com/oauth/authorize"
STRAVA_TOKEN_URL = "https://www.strava.com/api/v3/oauth/token"


# -----------------------------------------------
# Utilities to load/save secrets
# -----------------------------------------------
def load_secrets():
    if not os.path.exists(SECRETS_FILE):
        raise FileNotFoundError(f"{SECRETS_FILE} not found")
    with open(SECRETS_FILE, "r") as f:
        return json.load(f)


def save_secrets(data):
    with open(SECRETS_FILE, "w") as f:
        json.dump(data, f, indent=4)
    print("✓ Updated secrets.json")


# -----------------------------------------------
# Simple HTTP handler to catch OAuth redirect
# -----------------------------------------------
class OAuthHandler(http.server.SimpleHTTPRequestHandler):
    server_version = "StravaOAuthServer/1.0"

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        if "code" in params:
            self.server.auth_code = params["code"][0]

            self.send_response(200)
            self.send_header("Content-type", "text/html")
            self.end_headers()

            self.wfile.write(
                b"<h1>Authorization complete.</h1>"
                b"<p>You may close this tab and return to the terminal.</p>"
            )
        else:
            self.send_response(400)
            self.end_headers()
            self.wfile.write(b"Missing ?code parameter")


# -----------------------------------------------
# Start local HTTP server (in background thread)
# -----------------------------------------------
def start_local_server(port):
    handler = OAuthHandler
    httpd = socketserver.TCPServer(("", port), handler)

    # Store place for auth code
    httpd.auth_code = None

    thread = threading.Thread(target=httpd.serve_forever)
    thread.daemon = True
    thread.start()

    return httpd


# -----------------------------------------------
# Exchange auth code for tokens
# -----------------------------------------------
def exchange_code_for_tokens(client_id, client_secret, code, redirect_uri):
    resp = requests.post(
        STRAVA_TOKEN_URL,
        data={
            "client_id": client_id,
            "client_secret": client_secret,
            "code": code,
            "grant_type": "authorization_code",
            "redirect_uri": redirect_uri,
        },
    )
    resp.raise_for_status()
    return resp.json()


# -----------------------------------------------
# Validate tokens and scopes
# -----------------------------------------------
def validate_token(access_token):
    resp = requests.get(
        "https://www.strava.com/api/v3/athlete",
        headers={"Authorization": f"Bearer {access_token}"}
    )

    if resp.status_code != 200:
        print("⚠️ Token test failed:", resp.status_code, resp.text)
    else:
        print("✓ Token valid")
    return resp


# -----------------------------------------------
# Main OAuth flow
# -----------------------------------------------
def run_oauth(port=8000):
    secrets = load_secrets()

    client_id = secrets["client_id"]
    client_secret = secrets["client_secret"]

    redirect_uri = f"http://localhost:{port}/"

    # Start local server
    server = start_local_server(port)

    # Build OAuth URL
    auth_url = (
        f"{STRAVA_AUTH_URL}?"
        f"client_id={client_id}&"
        f"response_type=code&"
        f"redirect_uri={urllib.parse.quote(redirect_uri)}&"
        f"approval_prompt=force&"
        f"scope=read,activity:read_all"
    )

    print("Opening browser for Strava authorization...")
    print("If it does not open, paste this URL manually:")
    print(auth_url)

    # Open browser automatically
    webbrowser.open(auth_url)

    # Wait for redirect
    print("Waiting for authorization...")
    while server.auth_code is None:
        time.sleep(0.2)

    code = server.auth_code
    print("✓ Received authorization code")

    # Shut down the server
    server.shutdown()

    print("Exchanging code for tokens...")
    token_data = exchange_code_for_tokens(
        client_id, client_secret, code, redirect_uri
    )

    secrets["access_token"] = token_data["access_token"]
    secrets["refresh_token"] = token_data["refresh_token"]

    save_secrets(secrets)

    print("Testing access token...")
    validate_token(secrets["access_token"])

    print("🎉 OAuth setup complete!")


# -----------------------------------------------
# CLI entry
# -----------------------------------------------
if __name__ == "__main__":
    port = 8000
    if len(sys.argv) > 1:
        port = int(sys.argv[1])

    print(f"Starting Strava OAuth setup on port {port}...")
    run_oauth(port)
