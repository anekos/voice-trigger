# voice-trigger

PipeWire/PulseAudio 環境で、短い音(舌打ちなど)をトリガーに任意のコマンドを実行する CLI。

## インストール

```sh
make install
```

`uv tool install --force --reinstall .` を実行し、`voice-trigger` コマンドをユーザー環境にインストールする。

## 使い方

利用可能な入力ソースを確認する:

```sh
voice-trigger sources
```

閾値を調整する(実際に音を出しながらレベルを確認する。TRIGGER と表示された行が残るので、そこに出ているレベルを目安に `--threshold` を決める):

```sh
voice-trigger monitor -s SOURCE_NAME
```

1回検知したらコマンドを実行して終了する(ワンショット):

```sh
voice-trigger run -s SOURCE_NAME -t 0.3 -- notify-send "triggered"
```

`--timeout`(`-T`)を付けると、指定秒数以内に検知できなかった場合は終了コード非0で終わる:

```sh
voice-trigger run -s SOURCE_NAME -t 0.3 -T 10 -- notify-send "triggered"
```

COMMAND を省略すると、検知の有無だけを終了コードで表す(シェルスクリプトのゲートとして使える):

```sh
if voice-trigger run -s SOURCE_NAME -t 0.3 -T 10; then
  echo "detected"
else
  echo "timed out"
fi
```

検知するたびにコマンドを実行し続ける(`--loop`/`-l`。`--timeout`/`-T` とは併用不可):

```sh
voice-trigger run -s SOURCE_NAME -l -- notify-send "triggered"
```

`--cooldown`(`-c`。デフォルト0.5秒)は、`--loop` 使用時に1回の音で多重発火しないための不感時間。ワンショットモードでは検知した時点で即終了するため効果を持たない。

## 音声コマンド(listen)

特定のキーワードを音声認識して、対応するコマンドを実行する。設定は YAML(または JSON)で渡す。`commands` は必須で、1エントリは `keywords`(キーワードの配列。どれを認識しても発火する)と `command`(実行するコマンドの argv 配列)を持つ。`language` と `source` も設定ファイルに書ける:

```yaml
language: ja
commands:
  - keywords: [ブラウザ]
    command: [xdg-open, "https://example.com"]
  - keywords: [次, つぎ]
    command: [playerctl, next]
```

```sh
voice-trigger listen commands.yaml
```

YAML は JSON のスーパーセットなので、同じ構造の JSON ファイルもそのまま使える。

- 言語は `ja` または `en`。設定ファイルの `language` よりコマンドラインの `--language` が優先される(`source` と `-s` も同様)。どちらにも言語が無ければエラー。
- 対応する [Vosk](https://alphacephei.com/vosk/) モデル(~50MB)が無ければ初回に自動ダウンロードされる(保存先: `~/.local/share/voice-trigger/models/`)。
- 認識対象は JSON のキーワード + 未知語(`[unk]`)に制限されるため、無関係な発話では誤発火しにくい。
- キーワードに `"[unk]"` を指定すると、どのキーワードにもマッチしなかった発話(未知語)で発火するキャッチオールになる(無音では発火しない)。
- 認識結果とキーワードの照合は空白を無視して行う。
- 認識するたびに `heard: '認識結果' -> マッチしたキーワード` のログを表示する。
- `--dry-run` を付けるとログは同じだがコマンドは実行しない。キーワード表記の調整に使う。

```sh
voice-trigger listen commands.yaml --dry-run
```

## オプション一覧

| ロング形式 | ショート形式 | サブコマンド |
|---|---|---|
| `--source` | `-s` | run, monitor, listen |
| `--threshold` | `-t` | run, monitor |
| `--cooldown` | `-c` | run |
| `--timeout` | `-T` | run |
| `--loop` | `-l` | run |
| `--language` | | listen |
| `--dry-run` | | listen |

`listen` の設定ファイルはオプションではなく位置引数で渡す。
