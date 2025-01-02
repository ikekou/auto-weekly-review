#!/usr/bin/env python3
import os
import re
import argparse
from datetime import datetime

from loguru import logger
from dotenv import load_dotenv
import openai
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from google.auth.transport.requests import Request
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]

logger.add("report_tool.log", rotation="1 MB")

def get_google_service(service_name: str, version: str, credentials_file="credentials.json", token_file="token.json"):
    """
    OAuth認証を行い、指定のGoogle APIリソースを返す。
    credentials_file: OAuthクライアント情報（credentials.json）へのパス
    token_file: トークン情報（token.json）へのパス
    """
    creds = None

    if os.path.exists(token_file):
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(credentials_file, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(token_file, "w") as tf:
            tf.write(creds.to_json())

    return build(service_name, version, credentials=creds)

def fetch_documents(drive_service, folder_id, start_date, end_date):
    """
    指定フォルダ内のGoogle Docsを検索し、ファイル名が `YYYY年MM月DD日...` 形式で
    指定した日付範囲に該当するものを返す。
    """
    logger.info(f"Fetching documents from folder: {folder_id}")
    query = (
        f"'{folder_id}' in parents and "
        "mimeType='application/vnd.google-apps.document' and trashed=false"
    )

    try:
        response = drive_service.files().list(q=query, fields="files(id, name)").execute()
        items = response.get("files", [])
    except HttpError as err:
        logger.error(f"Error fetching documents list: {err}")
        return []

    matched_docs = []
    for item in items:
        filename = item["name"]
        match = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日.*", filename)
        if match:
            year, month, day = match.groups()
            try:
                doc_date = datetime.strptime(f"{year}-{month}-{day}", "%Y-%m-%d")
                if start_date <= doc_date <= end_date:
                    matched_docs.append(item)
            except ValueError:
                logger.warning(f"Invalid date in filename: {filename}")
        else:
            logger.debug(f"File not matching date pattern: {filename}")

    logger.info(f"Found {len(matched_docs)} documents in the date range.")
    return matched_docs

def extract_content(docs_service, document_id):
    """
    指定した document_id のGoogle Documentから本文を抽出し、文字列として返す。
    """
    logger.info(f"Extracting content from document ID: {document_id}")
    try:
        doc = docs_service.documents().get(documentId=document_id).execute()
    except HttpError as err:
        logger.error(f"Error retrieving doc content (ID={document_id}): {err}")
        return ""

    content_text = ""
    body = doc.get("body", {})
    for element in body.get("content", []):
        paragraph = element.get("paragraph")
        if paragraph and "elements" in paragraph:
            for el in paragraph["elements"]:
                text_run = el.get("textRun")
                if text_run and "content" in text_run:
                    content_text += text_run["content"]
    return content_text

def generate_report(all_text, model="gpt-4"):
    """
    指定したテキストからレポートを生成して返す。
    """
    openai.api_key = os.getenv("OPENAI_API_KEY")
    if not openai.api_key:
        logger.error("OPENAI_API_KEY is not set.")
        return "Error: OPENAI_API_KEY not configured."

    system_prompt = (
        "You are an advanced personal development assistant. "
        "Help the user gain deeper self-awareness and create practical 1-week action plans."
    )
    user_prompt = (
        "Here is the user's content:\n\n"
        f"{all_text}\n\n"
        "Please provide a thorough analysis and a clear one-week action plan."
    )

    try:
        response = openai.ChatCompletion.create(
            model=model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt}
            ],
            max_tokens=1500,
            temperature=0.7
        )
        return response["choices"][0]["message"]["content"].strip()
    except Exception as e:
        logger.error(f"Error calling OpenAI API: {e}")
        return "Error: could not generate a report."

def create_report_document(drive_service, docs_service, report_folder_id, report_name, report_content):
    """
    新しい Google Document を作成し、report_content を書き込む。
    """
    logger.info(f"Creating new report document: {report_name}")
    file_metadata = {
        "name": report_name,
        "mimeType": "application/vnd.google-apps.document",
        "parents": [report_folder_id]
    }

    try:
        new_doc = drive_service.files().create(body=file_metadata, fields="id").execute()
        doc_id = new_doc.get("id")

        requests = [
            {
                "insertText": {
                    "location": {"index": 1},
                    "text": report_content
                }
            }
        ]
        docs_service.documents().batchUpdate(documentId=doc_id, body={"requests": requests}).execute()
        logger.info(f"Report document created successfully (ID={doc_id}).")
    except HttpError as err:
        logger.error(f"Error creating/updating document: {err}")

def run_process(start_date, end_date, folder_id, report_folder_id):
    """
    main() から分離した実行関数。
    テスト時に、引数を直接指定してロジックを実行しやすくするために分離。
    """
    drive_service = get_google_service("drive", "v3")
    docs_service = get_google_service("docs", "v1")

    documents = fetch_documents(drive_service, folder_id, start_date, end_date)
    if not documents:
        logger.info("No documents found in the specified date range.")
        return

    combined_text = ""
    for doc in documents:
        doc_id = doc["id"]
        combined_text += extract_content(docs_service, doc_id) + "\n"

    report_content = generate_report(combined_text)
    report_name = f"レポート_{start_date.strftime('%Y-%m-%d')}_{end_date.strftime('%Y-%m-%d')}"
    create_report_document(drive_service, docs_service, report_folder_id, report_name, report_content)

def main():
    load_dotenv()

    parser = argparse.ArgumentParser(description="Generate a weekly report from Google Docs using OpenAI.")
    parser.add_argument("--start", required=True, help="Start date in YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date in YYYY-MM-DD")
    parser.add_argument("--folder-id", required=True, help="Google Drive folder ID to read docs from")
    parser.add_argument("--report-folder-id", required=True, help="Google Drive folder ID to save the report")

    args = parser.parse_args()

    try:
        start_date = datetime.strptime(args.start, "%Y-%m-%d")
        end_date = datetime.strptime(args.end, "%Y-%m-%d")
    except ValueError:
        logger.error("Invalid date format. Use YYYY-MM-DD.")
        return

    run_process(start_date, end_date, args.folder_id, args.report_folder_id)

if __name__ == "__main__":
    main()
