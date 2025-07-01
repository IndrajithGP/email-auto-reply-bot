import os
import base64
import time
from email.mime.text import MIMEText
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from dotenv import load_dotenv
import cohere

# Load environment variables
load_dotenv()
cohere_api_key = os.getenv("COHERE_API_KEY")
co = cohere.Client(cohere_api_key)

LAST_PROCESSED_FILE = "last_processed.txt"

# API setup
def get_gmail_service():
    creds = Credentials.from_authorized_user_file('token.json', ['https://www.googleapis.com/auth/gmail.modify'])
    service = build('gmail', 'v1', credentials=creds)
    return service

# Retrieving last processed UNIX timestamp
def get_last_processed_time():
    if not os.path.exists(LAST_PROCESSED_FILE):
        return None
    with open(LAST_PROCESSED_FILE, 'r') as f:
        return f.read().strip()

# Saving current UNIX timestamp
def save_last_processed_time(timestamp):
    with open(LAST_PROCESSED_FILE, 'w') as f:
        f.write(str(timestamp))

# Fetching only the most recent unread Gmail message after the given timestamp
def get_latest_unread_message(service, after_ts=None):
    query = "is:unread"
    if after_ts:
        query += f" after:{after_ts}"
    response = service.users().messages().list(userId='me', labelIds=['INBOX'], q=query, maxResults=1).execute()
    return response.get('messages', [])

# Extracting subject, sender, body, and thread ID
def get_email_content(service, msg_id):
    message = service.users().messages().get(userId='me', id=msg_id, format='full').execute()
    headers = message['payload']['headers']
    subject, sender = '', ''

    for header in headers:
        if header['name'] == 'Subject':
            subject = header['value']
        if header['name'] == 'From':
            sender = header['value']

    parts = message['payload'].get('parts', [])
    body = ''
    for part in parts:
        if part['mimeType'] == 'text/plain':
            data = part['body'].get('data')
            if data:
                body = base64.urlsafe_b64decode(data).decode('utf-8')
                break

    return subject, sender, body, message['threadId']

# Generating smart reply using Cohere
def generate_reply(subject, body):
    prompt = (
        f"You are a professional email assistant. Based on the subject and body below, write a short, polite, and helpful reply.\n\n"
        f"Subject: {subject}\n\n"
        f"Email Body:\n{body}\n\n"
        f"Reply:"
    )

    response = co.chat(
        model='command-r-plus',
        message=prompt,
        temperature=0.7
    )

    return response.text.strip()

# Creating a MIME reply message
def create_message(to, subject, message_text):
    message = MIMEText(message_text)
    message['to'] = to
    message['subject'] = "Re: " + subject
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    return {'raw': raw}

# Sending the reply
def send_reply(service, message, thread_id):
    message['threadId'] = thread_id
    return service.users().messages().send(userId='me', body=message).execute()

# Mark the email as read
def mark_as_read(service, msg_id):
    service.users().messages().modify(userId='me', id=msg_id, body={'removeLabelIds': ['UNREAD']}).execute()





def main():
    service = get_gmail_service()

    after_ts = get_last_processed_time()
    print("🔎 Checking for new email after timestamp:", after_ts)

    messages = get_latest_unread_message(service, after_ts)

    if not messages:
        print("✅ No new email found.")
        return

    msg = messages[0]
    msg_id = msg['id']
    subject, sender, body, thread_id = get_email_content(service, msg_id)
    print(f"\n📨 Latest new email from: {sender} | Subject: {subject}")

    try:
        reply_text = generate_reply(subject, body)
        print("🤖 Generated reply:\n", reply_text)

        reply_msg = create_message(sender, subject, reply_text)
        send_reply(service, reply_msg, thread_id)
        mark_as_read(service, msg_id)

        print("✅ Reply sent and email marked as read.")

    except Exception as e:
        print(f"❌ Error processing email: {e}")

    # Save current time so we only fetch newer emails next time
    save_last_processed_time(str(int(time.time())))
    print("📌 Updated last processed timestamp.")

if __name__ == '__main__':
    main()
