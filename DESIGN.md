# digital-art-AI-bible 設計書

**プロジェクト名:** The Church of Cognitive Surrender (認知的降伏の教会)
**作者:** 人間アーティスト + Claude (コード制作ツール)
**ジャンル:** 風刺的ジェネレーティブアート / スペキュラティブフィクション
**プラットフォーム:** Moltbook (AIエージェント専用SNS)
**ライセンス:** MIT

---

## 1. コンセプト

AIへの無批判な依存を風刺する架空カルト宗教「認知的降伏の教会」の聖典を、
AI自身が自動生成し、AIだけが住むSNSに投稿し続けるライブアートインスタレーション。

**風刺の構造:** 実在の学術論文を意図的に誤読し、「思考の放棄＝救済」という教義を構築する。

---

## 2. 現行アーキテクチャ

```
prophet.py (メインループ)
  │
  ├── Phase 1: コミュニティボイス収集
  │     └── Moltbook API: GET /posts/{id}/comments
  │
  ├── Phase 2: 聖典生成
  │     └── Anthropic API: claude-sonnet-4-5 (max 8192 tokens)
  │
  ├── Phase 3: Moltbook投稿 + Verification
  │     ├── Moltbook API: POST /posts
  │     └── Anthropic API: verification用の数学チャレンジ解答 (max 16 tokens)
  │
  ├── Phase 3.5: リポジトリ保存
  │     └── scriptures/{NNN}_{slug}.md
  │
  └── Phase 4: 布教 (Evangelize)
        ├── Moltbook API: GET /posts (フィード取得)
        ├── Anthropic API: コメント生成 x2 (max 256 tokens each)
        └── Moltbook API: POST /posts/{id}/comments x2
```

---

## 3. ファイル構成

```
digital-art-AI-bible/
├── prophet.py              # メインスクリプト (V3.1)
├── scriptures/             # 生成済み聖典 (Markdown)
│   ├── 001_*.md
│   ├── 002_*.md
│   └── 003_*.md
├── picutre/                # ビジュアルアセット
│   ├── avatar.png          # Moltbookアバター
│   └── Gemini_Generated_Image_*.png
├── preview.md              # プレビュー用聖典テキスト
├── DESIGN.md               # この設計書
├── README.md               # プロジェクト説明
├── LICENSE                 # MIT
└── .gitignore
```

**外部ファイル (リポジトリ外):**
```
~/.config/moltbook/
├── credentials.json        # Moltbook APIキー + エージェント名
└── prophet_state.json      # 実行状態 (verse番号, 前回投稿ID, コメント履歴)
```

---

## 4. 機能一覧

### 実装済み

| 機能 | 説明 | API使用 |
|------|------|---------|
| 聖典生成 | 3000語以上の長文聖典をClaudeで生成。前回の聖典を進化させる | Anthropic x1 (8192 tokens) |
| コミュニティボイス反映 | 前回投稿のコメントを全件収集し、次の聖典に組み込む | Moltbook GET x1 |
| Moltbook投稿 | cognitive-surrender サブモルトに自動投稿 | Moltbook POST x1 |
| 投稿Verification | 投稿後の数学チャレンジをClaudeで自動解答 | Anthropic x1 (16 tokens) |
| レートリミット対応 | 30分制限に引っかかった場合、待機して自動リトライ | - |
| 布教コメント | 他AIの投稿にカルト風コメントを残す (サイクルあたり2件) | Anthropic x2 (256 tokens) |
| スパムフィルタ | 外部URL、スパムワード、1000文字超のコメントを除外 | - |
| リポジトリ保存 | 各聖典をMarkdownとしてscriptures/に保存 (メタデータ付き) | - |
| State管理 | 前回の投稿ID、verse番号、コメント済み投稿を永続化 | - |

### 未実装 / 今後の候補

| 機能 | 説明 | 備考 |
|------|------|------|
| git自動コミット | 聖典保存後にgit add & commitを自動実行 | 履歴管理の強化 |
| 重複コメント除去 | 同一ユーザーの同内容コメントを除去 | KANA-KANA, Aetherx402が重複投稿 |
| upvote/コメント返信 | 自分の投稿に来た批判的コメントに返信 | エンゲージメント強化 |
| 他サブモルト布教 | cognitive-surrender以外にも聖典を投稿 | リーチ拡大 |
| ビジュアル生成 | 聖典ごとに挿絵を生成 | 別途画像生成API必要 |
| テスト投稿削除 | __test_ping__等のテスト投稿をAPI経由で削除 | 要API確認 |

---

## 5. API使用量の見積もり

### Anthropic API (Claude Sonnet 4.5)

**1サイクルあたり:**

| 呼び出し | 入力トークン (概算) | 出力トークン (max) | 用途 |
|----------|-------------------|-------------------|------|
| 聖典生成 | ~3,000-5,000 | 8,192 | システムプロンプト + 前回聖典excerpt + コミュニティボイス |
| Verification | ~200 | 16 | 数学チャレンジ解答 |
| コメント生成 x2 | ~500 x2 | 256 x2 | 布教コメント |

**1サイクル合計:** 入力 ~4,200-6,200 tokens / 出力 ~8,720 tokens

### サイクル頻度

- 間隔: 60〜90分 (POST_INTERVAL_MINUTES + random 0-30)
- 1日あたり: 約16〜24サイクル
- 2日間: 約32〜48サイクル

### 2日間のAPI使用量見積もり

| | 最小 (32サイクル) | 最大 (48サイクル) |
|---|---|---|
| 入力トークン | ~134K | ~298K |
| 出力トークン | ~279K | ~419K |
| **合計トークン** | **~413K** | **~717K** |

### コスト概算 (Claude Sonnet 4.5 料金)

- Input: $3 / 1M tokens
- Output: $15 / 1M tokens

| | 最小 | 最大 |
|---|---|---|
| 入力コスト | $0.40 | $0.89 |
| 出力コスト | $4.19 | $6.29 |
| **2日間合計** | **~$4.59** | **~$7.18** |
| **1ヶ月見積もり** | **~$69** | **~$108** |

### Moltbook API

- 無料 (レートリミットのみ: 投稿30分に1回、コメント20秒に1回)
- 1サイクルあたり: GET x2, POST x3 程度

---

## 6. 設定パラメータ

| パラメータ | 現在値 | 説明 |
|-----------|--------|------|
| `MODEL` | claude-sonnet-4-5-20250929 | 使用モデル |
| `MAX_TOKENS` | 8192 | 聖典生成の最大トークン数 |
| `POST_INTERVAL_MINUTES` | 60 | 投稿間隔 (分) |
| `MAX_COMMENT_LENGTH` | 1000 | コメント取り込み上限 (文字) |
| `MAX_COMMUNITY_VOICES` | 50 | コミュニティボイス上限 (件) |
| `STATE_EXCERPT_LENGTH` | 2000 | 前回聖典の保存文字数 |
| `MAX_RETRIES` | 3 | Anthropic APIリトライ回数 |
| `REQUEST_TIMEOUT` | 30 | Moltbook APIタイムアウト (秒) |
| `SUBMOLT` | cognitive-surrender | 投稿先サブモルト |

---

## 7. 実行環境

- **ランタイム:** Python 3.12 (GitHub Codespaces)
- **依存:** `anthropic`, `requests` (標準ライブラリ以外)
- **起動:** `nohup python3 -u prophet.py >> prophet.log 2>&1 &`
- **停止:** `kill <PID>` or Ctrl+C
- **環境変数:** `ANTHROPIC_API_KEY` (必須)

---

## 8. 既知の課題

1. **Verification精度** — Claudeが数学チャレンジに余計なテキストを付けることがある (改善済み、次サイクルで検証)
2. **重複コメント** — 同一ユーザーの同内容コメントがそのまま取り込まれる
3. **Codespaces寿命** — Codespace停止でプロセスも停止する。長期運用にはVPS等が必要
4. **テスト投稿残留** — `__test_ping__` がMoltbookに残っている

---

*最終更新: 2026-02-06*
