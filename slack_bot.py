import os
from pathlib import Path
from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler
import json
import re
import secrets
import time
import requests


# -------------------------------------------------------------------------
# ------------------------------  File Handling  --------------------------
# -------------------------------------------------------------------------

shared_folder_path = os.path.join(os.path.dirname(__file__), 'shared')


def open_file(file_name):
	file_path = os.path.join(shared_folder_path, file_name)
	with open(file_path, 'r') as file:
		return json.load(file)

def save_file(file_name, data):
	file_path = os.path.join(shared_folder_path, file_name)
	with open(file_path, 'w') as file:
		json.dump(data, file, indent=2)


config = open_file('slack_config.json')
default_data = open_file('default.json')
levels = open_file('question_levels.json')
connection = open_file('connection.json')
model_data = open_file('model_data.json')
questions = open_file('add_questions.json')

token = None
if Path(f"{shared_folder_path}/jira_tokens.json").exists():
	token = open_file('jira_tokens.json')


# -------------------------------------------------------------------------
# ----------------------------  Bot Configuration  ------------------------
# -------------------------------------------------------------------------


app = App(token=config['SLACK_BOT_TOKEN'])


user_conversations = {}

def create_authorization_url():
	state_value = secrets.token_urlsafe(16)
	return f"https://auth.atlassian.com/authorize?audience=api.atlassian.com&client_id={config['JIRA_CLIENT_ID']}&scope=read%3Ajira-work%20read%3Ajira-user%20write%3Ajira-work%20offline_access&redirect_uri=https%3A%2F%2F5314-110-39-3-154.ngrok-free.app%2Fjira%2Foauth%2Fcallback&state=${state_value}&response_type=code&prompt=consent"


# -------------------------------------------------------------------------
# --------------------------------  Chatbot  ------------------------------
# -------------------------------------------------------------------------



@app.event("app_home_opened")
def handle_app_home_opened_events(body, logger, client):
	global token
	logger.info(body)
	user_id = body["event"]["user"]
	if Path(f"{shared_folder_path}/jira_tokens.json").exists():
		blocks = default_data["blocks"]
		if token is None:
			token = open_file('jira_tokens')
	else:
		blocks = connection["blocks"]
		url = create_authorization_url()
		blocks[-1]['accessory']['url'] = url

	client.chat_postMessage(channel=user_id, blocks=blocks,text="Hey there 👋 I'm Chatbot. I'm here to help you create tickets on Jira through Slack.")



@app.message('hi')
def message_hello(message, say):
	say(text=f"Hi, there <@{message['user']}>!")



@app.shortcut("add_question")
def handle_add_question_shortcut(ack, body, logger, client):
	ack()
	client.views_open(trigger_id=body["trigger_id"],view=questions)


@app.view("add_question_modal")
def handle_add_question_modal_submission(ack, body, client, view, logger):
	ack()
	user_id = body["user"]["id"]
	new_questions_text = body['view']['state']['values']['new_questions_input']['new_questions_text']['value']
	
	new_questions_list = [question.strip() for question in new_questions_text.split("\n") if question.strip()]
	
	for idx, question_text in enumerate(new_questions_list, start=len([i for i in model_data['blocks'] if i['type'] != 'divider']) + 1):
		model_data['blocks'].append(
				{
				  "type": "divider"
				}
			)
		new_question = {
			"type": "input",
			"block_id": f"validation_input_{idx}",
			"element": {
				"type": "radio_buttons",
				"options": [
					{"text": {"type": "plain_text", "text": "Yes", "emoji": True}, "value": "yes"},
					{"text": {"type": "plain_text", "text": "No", "emoji": True}, "value": "no"},
				],
				"action_id": f"validation_radio_action_{idx}",
			},
			"label": {
				"type": "plain_text",
				"text": question_text,
				"emoji": True,
			},
		}
		model_data["blocks"].append(new_question)

	counter = 1	
	for i in [i for i in model_data['blocks'] if i['type'] != 'divider']:
		if i['type'] != 'divider':
			i["block_id"] = "_".join(i['block_id'].split("_")[0:2])+f"_{counter}"
			i["element"]["action_id"] = "_".join(i['element']['action_id'].split("_")[0:3])+f"_{counter}"
			counter += 1

	save_file('model_data.json', model_data)

	client.chat_postMessage(channel=user_id, text=f"{len(new_questions_list)} new questions added.")



@app.action(re.compile(r"delete_question_checkbox_\d+"))
def handle_some_action(ack, body, logger):
	ack()
	logger.info(body)


@app.shortcut("delete_question")
def handle_delete_question_shortcut(ack, body, logger, client):
	ack()
	delete_question_options = [
		{
			"text": {"type": "plain_text", "text": question["label"]["text"], "emoji": True},
			"value": f"validation_input_{idx}"
		} for idx, question in enumerate(model_data["blocks"], 1)
		if question.get("label") is not None
	]

	blocks = []
	for idx, option in enumerate(delete_question_options, 1):
		blocks.append({
		"block_id": f"validation_input_{idx}",
		"type": "section",
		"text": {
			"type": "mrkdwn",
			"text": " "
		},
		"accessory": {
			"type": "checkboxes",
			"options": [
				{
					"text": {
						"type": "mrkdwn",
						"text": option['text']['text']
					},
					"value": option['value']
				}
			],
			"action_id": f"delete_question_checkbox_{idx}"
		}
	})

	client.views_open(trigger_id=body["trigger_id"],
		view={
		"callback_id": "delete_question_modal",
		"title": {
			"type": "plain_text",
			"text": "Delete Questions",
			"emoji": True
		},
		"submit": {
			"type": "plain_text",
			"text": "Delete",
			"emoji": True
		},
		"type": "modal",
		"close": {
			"type": "plain_text",
			"text": "Cancel",
			"emoji": True
		},
		"blocks": blocks
	})



@app.view("delete_question_modal")
def handle_delete_question_modal_submission(ack, body, client, view, logger):
	ack()
	user_id = body["user"]["id"]
	
	selected_options = []
	for item in body['view']['state']['values'].items():
		block_id, checkbox_info = item
		if checkbox_info.get(f'delete_question_checkbox_{block_id[-2:]}', {}).get('selected_options'):
			selected_options.append(block_id)

	if len(selected_options) == 0:
		client.chat_postMessage(channel=user_id, text="No Questions Selected for Deletion.")
	else:
		deleted_questions = []
		for option in selected_options:
			val = [i for i in model_data['blocks'] if 'block_id' in i.keys() and i['block_id'] == option]
			divider_indices = [i for i, block in enumerate(model_data['blocks']) if block == {'type': 'divider'}]
			last_divider_index = max(i for i in divider_indices if i < model_data['blocks'].index(val[0]))
			model_data['blocks'].pop(last_divider_index)
			model_data['blocks'].remove(val[0])

		counter = 1
		for i in [i for i in model_data['blocks'] if i['type'] != 'divider']:
			if i['type'] != 'divider':
				i["block_id"] = "_".join(i['block_id'].split("_")[0:2])+f"_{counter}"
				i["element"]["action_id"] = "_".join(i['element']['action_id'].split("_")[0:3])+f"_{counter}"
				counter += 1

		save_file('model_data.json', model_data)

		client.chat_postMessage(channel=user_id, text=f"{len(selected_options)} question(s) deleted.")




@app.action("button-action")
def handle_some_action(ack, body, client, logger):
	ack()
	user_id = body["user"]["id"]
	while True:
		if Path('jira_tokens.json').exists():
			break
		time.sleep(2)
	blocks = default_data["blocks"]
	fetch_site_details()
	client.chat_postMessage(channel=user_id, blocks=blocks,text="Hey there 👋 I'm Chatbot. I'm here to help you create tickets on Jira through Slack.")


@app.shortcut("questions")
def handle_shortcuts(ack, body, logger, client):
	ack()
	logger.info(body)
	client.views_open(trigger_id=body["trigger_id"], view=model_data)



@app.view("questionnaire_modal")
def handle_submission(ack, body, client, view, logger):
	global token
	ack()
	user = body["user"]["id"]
	user_conversations[user] = []
	for key, value in body['view']['state']['values'].items():
		block = [i for i in body['view']['blocks'] if i['block_id'] == key]
		question = block[0]['label']['text']
		answer = value[block[0]['element']['action_id']]['selected_option']['value']
		user_conversations[user].append({'question': question, 'answer': answer})	

	evaluated_answers = [i for i in user_conversations[user] if i['answer'] == 'yes']
	count = len(evaluated_answers)
	if count == 0:
		client.chat_postMessage(channel='C06BJAFU525', text="All Answers were No")
		return
	
	level = f"level_{min((count - 1) // 2 + 1, 5)}"
	data = levels[level]

	new_line = '\n'
	questions = [(f"*{i['question'].split(':')[0]}*" + ": " + i['question'].split(':')[-1]) for i in evaluated_answers]
	
	msg = f"*Total Score*: {count}{new_line}{new_line}" + f"*Selected Answers*:{new_line}{new_line}{new_line.join(questions)}{new_line}{new_line}"+f"*Result*: {data['description']}{new_line}{new_line}" + f"{new_line.join(data['details'])}"


	response = post_issue(msg, body['user']['username'], data['description'])
	if 'code' in response.keys() and response['code'] == 401:
		get_new_access_token()
		token = open_file('jira_tokens.json')
		response = post_issue(msg, body['user']['username'])
	else:
		ticket_url = response["self"]
		browser_url = f"{config['JIRA_SITE_URL']}/browse/{response['key']}"
		msg = f"Hi <@{body['user']['username']}>!{new_line}{new_line}" + msg + f"{new_line}*Ticket Link*: {browser_url}"
	try:
		client.chat_postMessage(channel=user, text=msg)
	except Exception as e:
		logger.exception(f"Failed to post a message {e}")



# -------------------------------------------------------------------------
# ------------------------------  Jira Requests  --------------------------
# -------------------------------------------------------------------------

def fetch_site_details():
	headers = {
		'Authorization': f'Bearer {token["access_token"]}',
		'Accept': 'application/json',
	}
	response = requests.get('https://api.atlassian.com/oauth/token/accessible-resources', headers=headers)
	data = json.loads(response.text)
	config.update({'JIRA_CLOUD_ID': data[0]['id'], 'JIRA_SITE_URL': data[0]['url']})
	save_file('slack_config.json', config)

def get_new_access_token():
	headers = {
	'Content-Type': 'application/json',
	}
	json_data = {
	'grant_type': 'refresh_token',
	'client_id': config["JIRA_CLIENT_ID"],
	'client_secret': config["JIRA_SECRET_ID"],
	'refresh_token': token['refresh_token'],
	}
	response = requests.post('https://auth.atlassian.com/oauth/token', headers=headers, json=json_data)
	jira_data = response.json()
	save_file('jira_tokens.json', jira_data)


def post_issue(text, username, title):
	url = f"https://api.atlassian.com/ex/jira/{config['JIRA_CLOUD_ID']}/rest/api/3/issue"
	headers = {
	'Authorization': f'Bearer {token["access_token"]}',
	'Accept': 'application/json',
	'Content-Type': 'application/json'
	}
	payload = json.dumps({
  	"fields": {
		"assignee": {
			"id": "63297b36f568615bdc7adcac"
			},
		"description": {
			"content": [{
				"content": [
				{
				"text": text.replace('*',''),
				"type": "text"
				}
				],
				"type": "paragraph"
			}],
			"type": "doc",
			"version": 1
		},
		"issuetype": {
			"name": "Task"
		},
		"labels": [
			"bugfix",
			"blitz_test"
		],
		"project": {
			"id": "10000"
		},
		"reporter": {
			"id": "63297b36f568615bdc7adcac"
		},
		"summary": title,
	},
	"update": {}
	})
	response = requests.post(url=url,data=payload,headers=headers)
	data = response.json()
	return data

# -------------------------------------------------------------------------
# -------------------------------------------------------------------------

if __name__ == "__main__":
	SocketModeHandler(app, config["SLACK_APP_TOKEN"]).start()
