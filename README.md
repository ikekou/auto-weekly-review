以下は、同じディレクトリ内に `README.md` ファイルを作成するシェルスクリプト（`init_readme.sh` など）です。  
実行すると、`README.md` が新規作成され、すでに存在する場合は上書きしません。

---

```bash
#!/usr/bin/env bash

# ファイル名: init_readme.sh
# 実行方法:
#   chmod +x init_readme.sh
#   ./init_readme.sh
#
# このスクリプトを実行すると、README.md が作成されます。
# 既にファイルが存在する場合は中断します。

README_FILE="README.md"

if [ -f "$README_FILE" ]; then
  echo "Error: $README_FILE already exists. Aborting to avoid overwriting."
  exit 1
fi

cat << 'EOF' > "$README_FILE"
# auto-reviewer

## Overview
auto-reviewer は、指定期間内の Google Document を取得し、OpenAI の API（GPT-4 等）を使用してレポートを生成する CLI ツールです。  
ユーザーが記録した文章から自己理解を深めるための洞察を得たり、翌週の行動プランを検討するのに役立ちます。

## Features
- **Google Drive & Docs API 連携**  
  OAuth 認証により、指定されたフォルダ内の日付形式の Google Document を自動検索。
- **OpenAI (GPT-4 等) でレポート生成**  
  文章を解析し、気づきを促す分析や具体的なアクションプランを含むレポートを自動作成。
- **結果は Google Document に保存**  
  新たな Google Document をレポートフォルダに作成し、生成した内容を書き込みます。

## Setup
1. **Python のインストール**  
   - Python 3.8 以上を推奨します。
2. **リポジトリをクローン**  
   ```bash
   git clone <このリポジトリのURL>
   cd auto-reviewer
   ```
3. **必要なライブラリをインストール**  
   ```bash
   pip install -r requirements.txt
   ```
4. **Google Cloud Console で OAuth クライアント ID を作成し、credentials.json を取得**  
   - 「APIとサービス」→「認証情報」→「OAuth 2.0 クライアントID」からデスクトップアプリとして作成。
   - ダウンロードした `credentials.json` を本プロジェクト直下に配置し、`.gitignore` で管理外に。
5. **.env ファイルを作成**  
   - OpenAI の API キーを設定します（例: `OPENAI_API_KEY=sk-xxxxxxxxxxxxxx`）。  
   - `.gitignore` によりコミットから除外されます。
6. **Google Drive/Docs API を有効化**  
   - Google Cloud Console で「Drive API」「Docs API」を有効にしてください。

## Usage
以下はコマンド例です:
```bash
python main.py \
  --start 2024-01-01 \
  --end 2024-01-07 \
  --folder-id 1A2B3C4D5E6F7G8 \
  --report-folder-id 9Z8Y7X6W5V4U3T2
```
- `--start`, `--end` : レポート対象期間 (YYYY-MM-DD)
- `--folder-id` : 対象のGoogle DriveフォルダID（入力用）
- `--report-folder-id` : レポートを保存するGoogle DriveフォルダID（出力用）

初回実行時には OAuth 認証画面がブラウザで開きます。  
認証が成功すると `token.json` が生成され、2回目以降は自動的に再認証します。

## License
特に指定がなければ、[MIT License](LICENSE) や適宜ライセンスを設定してください。

## Notes
- `.env`, `credentials.json`, `token.json` など、機密性の高いファイルはリポジトリに含めないようご注意ください。
- 旧バージョンのOpenAIライブラリ (0.28.0) を使用しているため、最新の ChatCompletion API を使用する場合はバージョンアップを検討してください。
- 大量のテキストを扱う場合、トークン数の上限に注意し、必要に応じて分割処理を実装することも検討してください。
EOF

echo "$README_FILE has been created successfully."
```

---

### 使い方の手順

1. スクリプトをファイルに保存
   ```bash
   nano init_readme.sh
   ```
   上記内容を貼り付けて保存します。

2. 実行権限を付与
   ```bash
   chmod +x init_readme.sh
   ```

3. スクリプトを実行
   ```bash
   ./init_readme.sh
   ```
   - `README.md` が存在しない場合、新規作成されます。  
   - すでに `README.md` がある場合、上書きを防ぐためにエラーメッセージを出して終了します。