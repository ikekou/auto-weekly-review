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

    # システムプロンプト: 
    #   ChatGPTには英語で考えさせるが、最終的には日本語に翻訳して回答するよう指示。
    system_prompt = (
        "You are an advanced AI assistant with expertise in psychology, coaching, and behavioral science. "
        "You will reason in English internally to provide the best possible analysis, insights, and action plans "
        "for the user's personal development. However, after you finish your internal reasoning in English, "
        "you must translate your final answer into Japanese before outputting it to the user."
    )

    print(all_text)

    # ユーザープロンプト:
    #   ユーザーの記録を踏まえ、最高レベルの分析と提案を日本語で出力するよう要求。
    user_prompt = (
    "次のテキストは私の日記です。\n\n"
    + all_text
    + "\n\n"
    + "この日記をもとに、以下の観点から、具体的・行動可能なアドバイスを提示してください。\n"
    + "各分野の専門家の視点を想定し、特に次の点に留意して回答してください。\n"
    + "1) 信頼できる理論やエビデンスに基づいた助言\n"
    + "2) 誰でも取り組みやすい、具体的かつ行動可能なステップ\n"
    + "3) 短期・中期・長期の目標設定と、その達成に向けた行動計画\n"
    + "4) 追加で学べるリソース（本・ウェブサイト・専門家サービス等）の紹介\n"
    + "5) 振り返りや進捗確認の方法（記録アプリ・PDCAなど）\n"
    + "6) 翌週に実践できる行動リストの提示\n\n"
    + "【1. 全体要約】\n"
    + "   - 日記の主な出来事・トピック・感情を簡潔にまとめる\n"
    + "   - 重要・印象的なポイントを抽出（キーワードなど）\n\n"
    + "【2. メンタル面（心理学・カウンセリング・精神医学）】\n"
    + "   - ストレス要因・思考パターンを具体的に指摘し、認知行動療法（CBT）などの手法でどう対処できるか提案\n"
    + "   - 毎日のセルフケアとして実践できる呼吸法・瞑想・マインドフルネスなどの方法\n"
    + "   - 感情記録やリフレーミングに役立つワークシート・アプリ例\n"
    + "   - どんな状態・期間であれば専門家への相談を検討すべきか\n\n"
    + "【3. 健康面（医師・栄養士・トレーナー）】\n"
    + "   - 睡眠時間・食事バランス・運動頻度の見直しと具体的な改善ステップ（例：週3回30分のウォーキング）\n"
    + "   - スマホアプリやウェアラブル端末による健康管理の方法\n"
    + "   - 栄養面（野菜・たんぱく質・塩分・糖分）での具体的な改善策と目標設定\n"
    + "   - 必要に応じた検査や医療機関への受診タイミング\n\n"
    + "【4. キャリア面（キャリアコンサルタント・専門分野のプロ）】\n"
    + "   - 日記に表れている仕事・将来への不安を整理し、短期・中期・長期での目標を設定\n"
    + "   - スキルアップや業務効率向上に向けた学習・資格取得・オンライン講座などの提案\n"
    + "   - ネットワーキングや情報収集に活用できるプラットフォーム（SNS、コミュニティ）の紹介\n"
    + "   - キャリアの棚卸しや転職活動で有用なステップとタイミング\n\n"
    + "【5. 人間関係・コミュニケーション（コミュニケーションコーチ・心理学者）】\n"
    + "   - 日記から読み取れる対人関係の悩みの原因やパターンを分析\n"
    + "   - アサーションやアクティブリスニングなど、コミュニケーションを高めるための具体的技術\n"
    + "   - ロールプレイや対話記録による振り返り方法\n"
    + "   - 摩擦・衝突が生じたときの解決策や、建設的な話し合いに向けたガイド\n\n"
    + "【6. 時間管理・生産性（時間管理コンサルタント・プロダクティビティ専門家）】\n"
    + "   - 日記から見える時間の使い方や優先順位付けの問題を指摘\n"
    + "   - タイムブロッキング・ポモドーロ・タスクリストなどの生産性向上テクニック\n"
    + "   - 進捗管理のツールや習慣化のコツ（タスク管理アプリ・デジタルカレンダーなど）\n"
    + "   - 小さな目標の設定と達成感の積み重ねによるモチベーション維持\n\n"
    + "【7. 金銭管理・資産運用（ファイナンシャルプランナー・投資アドバイザー）】\n"
    + "   - 短期・長期の金銭的目標を見据えた家計管理（支出の最適化、貯蓄計画など）\n"
    + "   - インデックス投資や積立NISAなど、比較的リスクの低い資産形成方法\n"
    + "   - 家計簿アプリ・マネーセミナーなど、学習や管理に役立つリソース\n"
    + "   - 保険や税制面でのチェックポイント、ライフプラン全体を俯瞰したアドバイス\n\n"
    + "【8. その他の専門家の視点】\n"
    + "   - 上記以外で取り組めること（地域活動、趣味・教養、ボランティア、自己表現など）\n"
    + "   - 新しいチャレンジや交流を広げるためのイベント・SNSコミュニティ紹介\n"
    + "   - 自己成長につながる読書リストや学習プログラム\n\n"
    + "【9. まとめ】\n"
    + "   - 各分野の提案を簡潔に再確認\n"
    + "   - まず何から始めるべきか、行動の優先順位や最初の一歩を具体的に提示\n"
    + "   - 前向きな気持ちを引き出すような短い応援メッセージ\n\n"
    + "【10. 翌週にやるべき行動リスト】\n"
    + "   - 上記のアドバイスを参考に、具体的に行動へ移せるタスクを7日分程度リストアップ\n"
    + "   - 例：『月曜日: 30分ウォーキング』『火曜日: マインドフルネス瞑想を10分』『水曜日: ○○の講座を1時間受講』など\n"
    + "   - 日付（または曜日）ごとに行動を示し、習慣化しやすいように提案\n"
    + "   - うまくいかなかった場合のリカバリ案や、工夫の仕方も記載\n\n"
    + "【11. 継続と振り返り】\n"
    + "   - 実行後に振り返り・見直しをするための簡単なフレームワーク（PDCA、KPTなど）\n"
    + "   - 結果や気づきを記録するアプリ・ノートなどの活用例\n"
    + "   - 中長期的な成長のため、定期的に習慣の達成度を確認し、必要に応じて計画を修正\n\n"
    + "回答する際は、上記の構成に沿って箇条書きや段落分けを用い、わかりやすく整理してください。\n"
    + "私の日記に含まれる個人情報や機密情報には十分に配慮し、第三者に漏洩しないようお願いいたします。\n"
    )

    print(user_prompt)

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

    report_content = generate_report(combined_text,'gpt-4o')
    # print(report_content)
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
