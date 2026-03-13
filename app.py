import logging
import re
import requests
import os

from slack_bolt import App
from slack_bolt.adapter.socket_mode import SocketModeHandler

from flask import Flask, request
from slack_bolt.adapter.flask import SlackRequestHandler

logging.basicConfig(level=logging.INFO)

slack_app = App(
    token=os.environ["SLACK_BOT_TOKEN"],
    signing_secret=os.environ["SLACK_SIGNING_SECRET"]
)

flask_app = Flask(__name__)
handler = SlackRequestHandler(slack_app)

API_URL = "https://sailbslsafety.pythonanywhere.com/api/create-inspection-record"

modal_view = {
    "type": "modal",
    "callback_id": "inspection_submit",
    "title": {"type": "plain_text", "text": "Safety Inspection"},
    "submit": {"type": "plain_text", "text": "Submit"},
    "close": {"type": "plain_text", "text": "Cancel"},
    "private_metadata": "",   # ⭐ will be filled dynamically
    "blocks": [
        {
            "type": "input",
            "block_id": "date_block",
            "label": {"type": "plain_text", "text": "Inspection Date"},
            "element": {"type": "datepicker", "action_id": "date"}
        },
        {
            "type": "input",
            "block_id": "category_block",
            "label": {"type": "plain_text", "text": "Inspection Category"},
            "element": {"type": "plain_text_input", "action_id": "inspection_category"}
        },
        {
            "type": "input",
            "block_id": "department_block",
            "label": {"type": "plain_text", "text": "Department"},
            "element": {"type": "plain_text_input", "action_id": "department"}
        },
        {
            "type": "input",
            "block_id": "location_block",
            "label": {"type": "plain_text", "text": "Location"},
            "element": {"type": "plain_text_input", "action_id": "location"}
        },
        {
            "type": "input",
            "block_id": "observation_block",
            "label": {"type": "plain_text", "text": "Observation"},
            "element": {"type": "plain_text_input", "multiline": True, "action_id": "observation"}
        },
        {
            "type": "input",
            "block_id": "compliance_block",
            "label": {"type": "plain_text", "text": "Compliance Status"},
            "element": {
                "type": "static_select",
                "action_id": "compliance_status",
                "options": [
                    {"text": {"type": "plain_text","text": "Compliant"}, "value": "compliant"},
                    {"text": {"type": "plain_text","text": "Non-Compliant"}, "value": "non_compliant"}
                ]
            }
        },
        {
            "type": "input",
            "block_id": "discussed_block",
            "label": {"type": "plain_text", "text": "Discussed With"},
            "element": {"type": "plain_text_input", "action_id": "discussed_with"}
        },
        {
            "type": "input",
            "block_id": "target_date_block",
            "label": {"type": "plain_text", "text": "Target Date"},
            "element": {"type": "datepicker", "action_id": "target_date"}
        },
        {
            "type": "input",
            "block_id": "presentation_block",
            "label": {"type": "plain_text", "text": "Include in Presentation"},
            "element": {
                "type": "static_select",
                "action_id": "if_include_in_presentation",
                "options": [
                    {"text": {"type": "plain_text","text": "Yes"}, "value": "yes"},
                    {"text": {"type": "plain_text","text": "No"}, "value": "no"}
                ]
            }
        },
        {
            "type": "input",
            "block_id": "recommendation_block",
            "label": {"type": "plain_text", "text": "Recommendation"},
            "element": {"type": "plain_text_input", "multiline": True, "action_id": "recommendation"}
        },
        {
            "type": "input",
            "block_id": "photo_block",
            "label": {"type": "plain_text", "text": "Upload Photos"},
            "element": {
                "type": "file_input",
                "action_id": "photos",
                "filetypes": ["jpg","jpeg","png"],
                "max_files": 2
            }
        }
    ]
}

@slack_app.command("/inspection")
def open_modal(ack, body, client):
    ack()

    modal_view["private_metadata"] = body["channel_id"]

    client.views_open(
        trigger_id=body["trigger_id"],
        view=modal_view
    )

@slack_app.view("inspection_submit")
def handle_submission(ack, body, view, client, logger):

    ack()

    channel_id = view["private_metadata"]
    values = view["state"]["values"]

    inspection = {
        "date": values["date_block"]["date"]["selected_date"],
        "inspection_category": values["category_block"]["inspection_category"]["value"],
        "department": values["department_block"]["department"]["value"],
        "location": values["location_block"]["location"]["value"],
        "observation": values["observation_block"]["observation"]["value"],
        "compliance_status": values["compliance_block"]["compliance_status"]["selected_option"]["value"],
        "discussed_with": values["discussed_block"]["discussed_with"]["value"],
        "target_date": values["target_date_block"]["target_date"]["selected_date"],
        "if_include_in_presentation": values["presentation_block"]["if_include_in_presentation"]["selected_option"]["value"],
        "recommendation": values["recommendation_block"]["recommendation"]["value"]
    }

    files = values["photo_block"]["photos"]["files"]

    multipart_files = []

    for i, file in enumerate(files):
        info = client.files_info(file=file["id"])
        url = info["file"]["url_private"]

        headers = {
            "Authorization": f"Bearer {client.token}"
        }

        r = requests.get(url, headers=headers)

        multipart_files.append(
            (f"file{i}", ("photo.jpg", r.content, "image/jpeg"))
        )

    msg = client.chat_postMessage(
        channel=channel_id,
        text=f"""🚨 New Safety Inspection

    📅 {inspection['date']}
    🏭 {inspection['department']}
    📍 {inspection['location']}
    ⚠ {inspection['observation']}
    """
    )

    for file in files:
        info = client.files_info(file=file["id"])
        permalink = info["file"]["permalink"]

        client.chat_postMessage(
            channel=channel_id,
            thread_ts=msg["ts"],
            text=f"📷 {permalink}"
        )

    try:
        response = requests.post(
            API_URL,
            data=inspection,
            files=multipart_files,
            timeout=30
        )

        if response.status_code in [200, 201]:
            logger.info(f"Observation saved successfully. Status: {response.status_code}")
            client.chat_postMessage(
                channel=channel_id,
                thread_ts=msg["ts"],
                text="✅ Observation saved successfully in the database!"
            )            

        else:
            logger.error(
                f"Failed to save observation. "
                f"Status: {response.status_code}, "
                f"Response: {response.text}"
            )

            client.chat_postMessage(
                channel=channel_id,
                thread_ts=msg["ts"],
                text=f"❌ Database Error\nStatus: {response.status_code}"
            )

    except requests.exceptions.RequestException as e:
        logger.exception("Network/API error while saving inspection")

        client.chat_postMessage(
            channel=channel_id,
            thread_ts=msg["ts"],
            text="❌ Network Error: Could not reach backend API"
        )

# -------- HTTP ROUTE --------
# HEALTH CHECK ROUTE (Render + Slack test)
@flask_app.route("/", methods=["GET"])
def health():
    return "running", 200

# SLACK EVENTS ROUTE
@flask_app.route("/slack/events", methods=["POST"])
def slack_events():

    body = request.get_json(silent=True)

    # URL verification
    if body and body.get("type") == "url_verification":
        return jsonify({"challenge": body["challenge"]})

    return handler.handle(request)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 10000))
    flask_app.run(host="0.0.0.0", port=port)
