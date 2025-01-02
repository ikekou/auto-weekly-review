# test_main.py
import os
import pytest
from unittest.mock import patch, MagicMock
from datetime import datetime

import main  # main.py をインポート

@pytest.fixture
def mock_env(monkeypatch):
    # 環境変数設定（OPENAI_API_KEY等）
    monkeypatch.setenv("OPENAI_API_KEY", "sk-fake-key")

#-------------------------------------------------
# fetch_documents のテスト例
#-------------------------------------------------
@patch("main.logger")
def test_fetch_documents(mock_logger, mock_env):
    # Drive API の mock
    drive_service = MagicMock()
    drive_service.files().list().execute.return_value = {
        "files": [
            {"id": "doc1", "name": "2024年01月02日水曜日"},
            {"id": "doc2", "name": "2024年01月03日木曜日"},
            {"id": "doc3", "name": "invalid_file_name"}
        ]
    }

    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 3)

    result = main.fetch_documents(drive_service, "folder123", start_date, end_date)
    assert len(result) == 2  # 2つだけマッチする
    assert result[0]["id"] == "doc1"
    assert result[1]["id"] == "doc2"

    # ログが呼ばれているか確認
    mock_logger.info.assert_any_call("Fetching documents from folder: folder123")
    mock_logger.info.assert_any_call("Found 2 documents in the date range.")

#-------------------------------------------------
# extract_content のテスト例
#-------------------------------------------------
@patch("main.logger")
def test_extract_content(mock_logger, mock_env):
    docs_service = MagicMock()
    docs_service.documents().get().execute.return_value = {
        "body": {
            "content": [
                {"paragraph": {"elements": [
                    {"textRun": {"content": "Hello "}},
                    {"textRun": {"content": "World"}}
                ]}},
                {"paragraph": {"elements": [
                    {"textRun": {"content": "\nAnother line"}}
                ]}}
            ]
        }
    }

    content = main.extract_content(docs_service, "doc1")
    assert content == "Hello World\nAnother line"
    mock_logger.info.assert_called_with("Extracting content from document ID: doc1")

#-------------------------------------------------
# generate_report のテスト例
#-------------------------------------------------
@patch("main.logger")
@patch("openai.ChatCompletion.create")
def test_generate_report(mock_chat_completion, mock_logger, mock_env):
    # ChatCompletion.create のモック
    mock_chat_completion.return_value = {
        "choices": [
            {"message": {"content": "This is a fake report content."}}
        ]
    }

    report = main.generate_report("Sample text")
    assert "fake report content" in report

    mock_chat_completion.assert_called_once()
    mock_logger.error.assert_not_called()  # エラーが出ていないこと

#-------------------------------------------------
# create_report_document のテスト例
#-------------------------------------------------
@patch("main.logger")
def test_create_report_document(mock_logger, mock_env):
    drive_service = MagicMock()
    docs_service = MagicMock()

    # Drive API の返り値をモック
    drive_service.files().create().execute.return_value = {"id": "new_doc_id"}

    main.create_report_document(drive_service, docs_service, "report_folder", "Test Report", "Report Content")

    # Drive API の呼び出しを検証
    drive_service.files().create.assert_called_once()
    docs_service.documents().batchUpdate.assert_called_once()

    mock_logger.info.assert_any_call("Creating new report document: Test Report")
    mock_logger.info.assert_any_call("Report document created successfully (ID=new_doc_id).")

#-------------------------------------------------
# run_process のテスト例
#-------------------------------------------------
@patch("main.get_google_service")
@patch("main.fetch_documents")
@patch("main.extract_content")
@patch("main.generate_report")
@patch("main.create_report_document")
@patch("main.logger")
def test_run_process(mock_logger,
                     mock_create_report_document,
                     mock_generate_report,
                     mock_extract_content,
                     mock_fetch_documents,
                     mock_get_google_service,
                     mock_env):
    # それぞれのモックを設定
    drive_service_mock = MagicMock()
    docs_service_mock = MagicMock()

    mock_get_google_service.side_effect = [drive_service_mock, docs_service_mock]

    # fetch_documents の返り値
    mock_fetch_documents.return_value = [
        {"id": "doc1", "name": "2024年01月02日水曜日"}
    ]
    # extract_content の返り値
    mock_extract_content.return_value = "Some doc content"
    # generate_report の返り値
    mock_generate_report.return_value = "Final Report Content"

    start_date = datetime(2024, 1, 1)
    end_date = datetime(2024, 1, 3)
    folder_id = "folder123"
    report_folder_id = "report123"

    main.run_process(start_date, end_date, folder_id, report_folder_id)

    # アサーション
    mock_get_google_service.assert_any_call("drive", "v3")
    mock_get_google_service.assert_any_call("docs", "v1")
    mock_fetch_documents.assert_called_once_with(drive_service_mock, folder_id, start_date, end_date)
    mock_extract_content.assert_called_once_with(docs_service_mock, "doc1")
    mock_generate_report.assert_called_once_with("Some doc content\n")
    mock_create_report_document.assert_called_once_with(
        drive_service_mock, docs_service_mock, report_folder_id,
        "レポート_2024-01-01_2024-01-03", "Final Report Content"
    )

    mock_logger.info.assert_any_call("No documents found in the specified date range.") if not mock_fetch_documents else None
