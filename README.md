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

## オプション一覧

| ロング形式 | ショート形式 | サブコマンド |
|---|---|---|
| `--source` | `-s` | run, monitor |
| `--threshold` | `-t` | run, monitor |
| `--cooldown` | `-c` | run |
| `--timeout` | `-T` | run |
| `--loop` | `-l` | run |
