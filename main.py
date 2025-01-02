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

# Google API のスコープ（Drive, Docs へのフルアクセス）
SCOPES = [
    "https://www.googleapis.com/auth/drive",
    "https://www.googleapis.com/auth/documents",
]

# ログ設定：report_tool.log に出力し、1MB超過でローテーション
logger.add("report_tool.log", rotation="1 MB")

def get_google_service(service_name: str, version: str):
    """
    credentials.json を用いた OAuth 認証を行い、指定の Google API リソースを返す。
    初回実行時はブラウザを開いて認証 → token.json にトークンを保存。
    2回目以降は token.json を再利用して認証を自動的に更新する。
    """
    creds = None
    token_path = "token.json"

    # 既存トークンがあれば読み込む
    if os.path.exists(token_path):
        creds = Credentials.from_authorized_user_file(token_path, SCOPES)

    # 未認証 or 有効期限切れの場合は OAuth フローを実行
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file("credentials.json", SCOPES)
            creds = flow.run_local_server(port=0)
        # 新しいトークンを保存
        with open(token_path, "w") as token_file:
            token_file.write(creds.to_json())

    return build(service_name, version, credentials=creds)

def fetch_documents(drive_service, folder_id, start_date, end_date):
    """
    指定フォルダ（folder_id）内にあるGoogle Documentの一覧を取得し、
    ファイル名が「YYYY年MM月DD日...」形式で指定期間内に該当するものを返す。
    """
    logger.info(f"Fetching documents from folder: {folder_id}")
    query = (
        f"'{folder_id}' in parents "
        "and mimeType='application/vnd.google-apps.document' "
        "and trashed=false"
    )

    try:
        response = drive_service.files().list(
            q=query,
            fields="files(id, name)"
        ).execute()
        items = response.get("files", [])
    except HttpError as err:
        logger.error(f"Error fetching documents list: {err}")
        return []

    documents = []
    for item in items:
        filename = item["name"]
        # 例: 2024年1月2日木曜日 → ^(\d{4})年(\d{1,2})月(\d{1,2})日.*
        match = re.match(r"^(\d{4})年(\d{1,2})月(\d{1,2})日.*", filename)
        if match:
            year, month, day = match.group(1), match.group(2), match.group(3)
            try:
                doc_date = datetime.strptime(f"{year}-{month}-{day}", "%Y-%m-%d")
                if start_date <= doc_date <= end_date:
                    documents.append(item)
            except ValueError:
                logger.warning(f"Filename matched regex but date is invalid: {filename}")
        else:
            logger.debug(f"File not matching date format: {filename}")

    logger.info(f"Found {len(documents)} documents in the specified date range.")
    return documents

def extract_content(docs_service, document_id):
    """
    指定したGoogle Document (document_id) から本文テキストを抽出し、返す。
    """
    logger.info(f"Extracting content from document ID: {document_id}")
    text_content = ""
    try:
        doc = docs_service.documents().get(documentId=document_id).execute()
        body = doc.get("body", {})
        for element in body.get("content", []):
            paragraph = element.get("paragraph")
            if paragraph and "elements" in paragraph:
                for el in paragraph["elements"]:
                    text_run = el.get("textRun")
                    if text_run and "content" in text_run:
                        text_content += text_run["content"]
    except HttpError as err:
        logger.error(f"Error retrieving doc content (ID={document_id}): {err}")
    return text_content

def generate_report(all_text):
    """
    ChatCompletion API (model=gpt-4) を使用してレポートを生成する。
    - 自己理解を深めるための気づき
    - 1週間の具体的なアクションプラン
    """
    openai.api_key = os.getenv("OPENAI_API_KEY")
    if not openai.api_key:
        logger.error("OPENAI_API_KEY not found. Please set it in .env or as an environment variable.")
        return "Error: OPENAI_API_KEY is not configured."

    # --- システムプロンプト ---
    system_prompt = (
        "You are an advanced personal development assistant, skilled in helping users"
        " gain deeper self-awareness and create practical action plans based on their"
        " daily notes. Your goal is to help the user uncover hidden aspects or patterns"
        " they may not notice, and guide them to a concrete 1-week plan to address"
        " opportunities or challenges. Provide thoughtful insights and constructive,"
        " realistic next steps."
    )

    # --- ユーザープロンプト ---
    # ゼロベースで考えた、ユーザーが「自分のことを深く知り、次に何をすべきか」を導くための構成例
    user_content = (
        "Below is the user's journal or daily records for the specified period."
        " Please read it carefully, and produce a thorough review that includes:\n\n"
        "1. Key Observations:\n"
        "   - Summarize the main themes, trends, and recurring patterns.\n"
        "2. Self-Awareness & Hidden Insights:\n"
        "   - Highlight any emotional/behavioral patterns the user might not realize.\n"
        "   - Discuss potential root causes or motivations.\n"
        "3. Reflection & Next Steps:\n"
        "   - Suggest how the user can reflect on these insights to learn more about themselves.\n"
        "   - Offer a clear and concrete 1-week action plan with steps for improvement,\n"
        "     habit formation, or problem-solving.\n\n"
        "Be sure the final output helps the user gain new self-awareness and practical"
        " guidance for the coming week.\n\n"
        f"{all_text}"
    )

    try:
        response = openai.ChatCompletion.create(
            model="gpt-4",  # GPT-4モデルを利用
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_content}
            ],
            max_tokens=2500,  # より詳しい内容を期待してトークン数を増やす
            temperature=0.7   # 創造性と安定性のバランス
        )
        generated_text = response["choices"][0]["message"]["content"].strip()
        logger.info("OpenAI API call succeeded.")
        return generated_text
    except Exception as e:
        logger.error(f"Error calling OpenAI ChatCompletion: {e}")
        return "Error: could not generate a report."

def create_report_document(drive_service, docs_service, report_folder_id, report_name, report_content):
    """
    report_folder_id に新しいGoogle Documentを作成し、report_content を書き込む。
    """
    logger.info(f"Creating new report document: {report_name}")
    file_metadata = {
        "name": report_name,
        "mimeType": "application/vnd.google-apps.document",
        "parents": [report_folder_id]
    }

    try:
        # 空のDocを作成 (Drive API)
        new_doc = drive_service.files().create(
            body=file_metadata,
            fields="id"
        ).execute()
        doc_id = new_doc.get("id")

        # Docs API を使って本文を書き込む
        requests = [
            {
                "insertText": {
                    "location": {"index": 1},
                    "text": report_content
                }
            }
        ]
        docs_service.documents().batchUpdate(
            documentId=doc_id,
            body={"requests": requests}
        ).execute()
        logger.info(f"Report document created successfully (ID={doc_id}).")
    except HttpError as err:
        logger.error(f"Error creating/updating document: {err}")

def main():
    load_dotenv()  # .env から環境変数読み込み（OPENAI_API_KEYなど）

    parser = argparse.ArgumentParser(
        description="Generate a self-awareness and next-step report from Google Docs using OpenAI ChatCompletion (GPT-4)."
    )
    parser.add_argument("--start", required=True, help="Start date in YYYY-MM-DD")
    parser.add_argument("--end", required=True, help="End date in YYYY-MM-DD")
    parser.add_argument("--folder-id", required=True, help="Google Drive folder ID for source docs")
    parser.add_argument("--report-folder-id", required=True, help="Google Drive folder ID to save the report")
    args = parser.parse_args()

    # 日付のパース
    try:
        start_date = datetime.strptime(args.start, "%Y-%m-%d")
        end_date = datetime.strptime(args.end, "%Y-%m-%d")
    except ValueError:
        logger.error("Invalid date format. Use YYYY-MM-DD.")
        return

    logger.info("Initializing Google API services...")
    drive_service = get_google_service("drive", "v3")
    docs_service = get_google_service("docs", "v1")

    # 指定範囲内に該当するドキュメントを検索
    documents = fetch_documents(drive_service, args.folder_id, start_date, end_date)
    if not documents:
        logger.info("No documents found within the specified date range.")
        return

    # 対象ドキュメントの本文をすべて結合
    combined_text = ""
    for doc in documents:
        doc_id = doc["id"]
        doc_content = extract_content(docs_service, doc_id)
        combined_text += doc_content + "\n"

    # OpenAI ChatCompletion (GPT-4) でレポート生成
    report_content = generate_report(combined_text)

    # レポート名を作成
    report_name = f"レポート_{args.start}_{args.end}"

    # 新しいGoogle Documentを作り、レポートを書き込む
    create_report_document(drive_service, docs_service, args.report_folder_id, report_name, report_content)

    logger.info(f"Process completed. Report saved as: {report_name}")

if __name__ == "__main__":
    main()
