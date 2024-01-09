from flask import Flask, request, jsonify
import requests
import json
import os

shared_folder_path = os.path.join(os.path.dirname(__file__), 'shared')


app = Flask(__name__)


def load_shared_file(file_name):
    file_path = os.path.join(shared_folder_path, file_name)
    with open(file_path, 'r') as file:
        return json.load(file)

config = load_shared_file('slack_config.json')

@app.route('/jira/oauth/callback', methods=['GET'])
def jira_oauth_callback():
    code = request.args.get('code')

    headers = {
    'Content-Type': 'application/json',
    }

    json_data = {
        'grant_type': 'authorization_code',
        'client_id': config["JIRA_CLIENT_ID"],
        'client_secret': config["JIRA_SECRET_ID"],
        'code': code,
        'redirect_uri': 'https://5314-110-39-3-154.ngrok-free.app/jira/oauth/callback',
    }

    response = requests.post('https://auth.atlassian.com/oauth/token', headers=headers, json=json_data)

    jira_data = response.json()
    file_path = os.path.join(shared_folder_path, 'jira_tokens.json')
    with open(file_path, "w") as file:
        json.dump(jira_data, file, indent=2)

    return 'Jira OAuth callback received successfully.'


if __name__ == '__main__':
    app.run(port=3000)
