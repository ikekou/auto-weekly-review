# test_main.py
import os
import pytest
from unittest.mock import patch, MagicMock, call
from datetime import datetime

import main  # リファクタリング済みの main.py をインポート


@pytest.fixture
def mock_env(monkeypatch):
    """
    テスト用の環境変数を設定する Pytest fixture。
    例: OPENAI_API_KEY をダミーで設定。
    """
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-key")


@patch("main.logger")
def test_fetch_documents(mock_logger, mock_env):
    """
    fetch_documents() が Drive API 結果を正しくフィルタリングするか確認。
    """
    drive_service = MagicMock()
    # Drive API のモック返り値
    drive_service.files().list().execute.return_value = {
        "files": [
            {"id": "doc1", "name": "2024年01月02日木曜日"},
            {"id": "doc2", "name": "2024年01月03日金曜日"},
            {"id": "doc3", "name": "invalid_filename"}
        ]
    }

    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 3)

    result = main.fetch_documents(drive_service, "folder123", start_date, end_date)

    # doc1, doc2 がマッチし、doc3 はマッチしない
    assert len(result) == 2
    assert result[0]["id"] == "doc1"
    assert result[1]["id"] == "doc2"

    # ログ出力の確認
    mock_logger.info.assert_any_call("Fetching documents from folder: folder123")
    mock_logger.info.assert_any_call("Found 2 documents in the date range.")


@patch("main.logger")
def test_extract_content(mock_logger, mock_env):
    """
    extract_content() が Docs API 結果からテキスト要素を正しく取得するか確認。
    """
    docs_service = MagicMock()
    docs_service.documents().get().execute.return_value = {
        "body": {
            "content": [
                {
                    "paragraph": {
                        "elements": [
                            {"textRun": {"content": "Hello "}},
                            {"textRun": {"content": "World"}}
                        ]
                    }
                },
                {
                    "paragraph": {
                        "elements": [
                            {"textRun": {"content": "\nAnother line"}}
                        ]
                    }
                }
            ]
        }
    }

    content = main.extract_content(docs_service, "doc123")
    assert content == "Hello World\nAnother line"
    mock_logger.info.assert_called_with("Extracting content from document ID: doc123")


@patch("main.logger")
@patch("openai.ChatCompletion.create")
def test_generate_report(mock_chat_completion, mock_logger, mock_env):
    """
    generate_report() が OpenAI API からの応答を正しく処理するか確認。
    """
    # ChatCompletion.create のモック返り値
    mock_chat_completion.return_value = {
        "choices": [
            {"message": {"content": "AI-generated report content."}}
        ]
    }

    sample_input = "Sample daily records."
    report = main.generate_report(sample_input, model="gpt-4")

    assert "AI-generated report content." in report
    mock_chat_completion.assert_called_once()
    mock_logger.error.assert_not_called()


@patch("main.logger")
def test_create_report_document(mock_logger, mock_env):
    """
    create_report_document() が Drive API でドキュメントを生成し、
    Docs API で本文を書き込む呼び出しをしているか確認。
    """
    drive_service = MagicMock()
    docs_service = MagicMock()

    # drive_service.files().create().execute() の戻り値を設定
    create_mock = drive_service.files().create.return_value
    create_mock.execute.return_value = {"id": "new_doc_id"}

    main.create_report_document(
        drive_service,
        docs_service,
        "report_folder",
        "Test Report",
        "Report Content"
    )

    # 1) create() の呼び出し
    drive_service.files().create.assert_called_once_with(
        body={
            'name': 'Test Report',
            'mimeType': 'application/vnd.google-apps.document',
            'parents': ['report_folder']
        },
        fields='id'
    )

    # 2) create() の戻り値 => execute()
    create_mock.execute.assert_called_once()

    # 3) batchUpdate の呼び出し
    docs_service.documents().batchUpdate.assert_called_once_with(
        documentId='new_doc_id',
        body={
            'requests': [
                {
                    'insertText': {
                        'location': {'index': 1},
                        'text': 'Report Content'
                    }
                }
            ]
        }
    )

    mock_logger.info.assert_any_call("Creating new report document: Test Report")
    mock_logger.info.assert_any_call("Report document created successfully (ID=new_doc_id).")


@patch("main.logger")
@patch("main.create_report_document")
@patch("main.generate_report")
@patch("main.extract_content")
@patch("main.fetch_documents")
@patch("main.get_google_service")
def test_run_process(
    mock_get_google_service,
    mock_fetch_documents,
    mock_extract_content,
    mock_generate_report,
    mock_create_report_document,
    mock_logger,
    mock_env
):
    """
    run_process() が各関数を正しく呼び出し、フローを完了するか確認。
    """
    # mock たちの設定
    drive_service_mock = MagicMock()
    docs_service_mock = MagicMock()

    # get_google_service の返り値を差し替え (順番に呼ばれる)
    mock_get_google_service.side_effect = [drive_service_mock, docs_service_mock]

    # fetch_documents の返り値
    mock_fetch_documents.return_value = [
        {"id": "docA", "name": "2024年01月02日"},
        {"id": "docB", "name": "2024年01月03日"}
    ]

    # extract_content の返り値
    mock_extract_content.side_effect = ["ContentA", "ContentB"]

    # generate_report の返り値
    mock_generate_report.return_value = "Final Report"

    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 7)
    folder_id = "folderXYZ"
    report_folder_id = "folderOUT"

    main.run_process(start_date, end_date, folder_id, report_folder_id)

    # get_google_service は drive と docs を呼び出しているはず
    mock_get_google_service.assert_any_call("drive", "v3")
    mock_get_google_service.assert_any_call("docs", "v1")

    # fetch_documents が呼ばれ、2つの doc を返す
    mock_fetch_documents.assert_called_once_with(drive_service_mock, folder_id, start_date, end_date)
    assert mock_fetch_documents.return_value == [
        {"id": "docA", "name": "2024年01月02日"},
        {"id": "docB", "name": "2024年01月03日"}
    ]

    # extract_content は docA, docB を順番に呼び出す
    mock_extract_content.assert_any_call(docs_service_mock, "docA")
    mock_extract_content.assert_any_call(docs_service_mock, "docB")

    # generate_report は ContentA + \n + ContentB で呼ばれる
    mock_generate_report.assert_called_once_with("ContentA\nContentB\n")

    # create_report_document の呼び出し
    mock_create_report_document.assert_called_once_with(
        drive_service_mock,
        docs_service_mock,
        report_folder_id,
        "レポート_2024-01-01_2024-01-07",
        "Final Report"
    )

    # ログメッセージのチェック
    mock_logger.info.assert_any_call("No documents found in the specified date range.") if not mock_fetch_documents else None

if __name__ == "__main__":
    print("Running tests...")
    pytest.main()
