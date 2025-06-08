import os
import requests
from flask import Blueprint, request, jsonify

azure_bot_bp = Blueprint('azure_bot', __name__)

# Get Azure Bot credentials from environment variables
AZURE_BOT_ID = os.environ.get("MicrosoftAppId")
AZURE_BOT_PASSWORD = os.environ.get("MicrosoftAppPassword")
DIRECTLINE_SECRET = os.environ.get("DirectLineSecret")  # You need to set this in your Azure Bot resource
DIRECTLINE_URL = "https://directline.botframework.com/v3/directline/conversations"

# Start a new conversation with the Azure Bot
@azure_bot_bp.route('/api/azure-bot', methods=['POST'])
def talk_to_azure_bot():
    data = request.get_json()
    user_message = data.get('message')
    if not user_message:
        return jsonify({'error': 'No message provided'}), 400
    if not DIRECTLINE_SECRET:
        return jsonify({'error': 'DirectLine secret not configured'}), 500

    # Start a conversation
    headers = {
        'Authorization': f'Bearer {DIRECTLINE_SECRET}',
        'Content-Type': 'application/json'
    }
    conv_response = requests.post(DIRECTLINE_URL, headers=headers)
    if conv_response.status_code != 201:
        return jsonify({'error': 'Failed to start conversation with Azure Bot'}), 500
    conv_id = conv_response.json()['conversationId']

    # Send user message
    activity = {
        "type": "message",
        "from": {"id": "user1"},
        "text": user_message
    }
    send_url = f"{DIRECTLINE_URL}/{conv_id}/activities"
    send_response = requests.post(send_url, headers=headers, json=activity)
    if send_response.status_code not in (200, 201):
        return jsonify({'error': 'Failed to send message to Azure Bot'}), 500

    # Poll for bot response
    activities_url = f"{DIRECTLINE_URL}/{conv_id}/activities"
    bot_reply = None
    for _ in range(10):  # Try a few times
        activities_response = requests.get(activities_url, headers=headers)
        if activities_response.status_code == 200:
            activities = activities_response.json().get('activities', [])
            bot_activities = [a for a in activities if a.get('from', {}).get('id') != 'user1' and a.get('type') == 'message']
            if bot_activities:
                bot_reply = bot_activities[-1]['text']
                break
    if not bot_reply:
        bot_reply = "Sorry, I didn't get a response from the Azure Bot."
    return jsonify({'response': bot_reply})
