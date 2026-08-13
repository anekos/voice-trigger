# voice-trigger

PipeWire/PulseAudio 環境で、短い音(舌打ちなど)をトリガーに任意のコマンドを実行する CLI。

## 使い方

利用可能な入力ソースを確認する:

```sh
voice-trigger sources
```

閾値を調整する(実際に音を出しながらレベルを確認する):

```sh
voice-trigger monitor --source SOURCE_NAME
```

1回検知したらコマンドを実行して終了する:

```sh
voice-trigger run --source SOURCE_NAME --threshold 0.3 -- notify-send "triggered"
```

検知するたびにコマンドを実行し続ける:

```sh
voice-trigger run --source SOURCE_NAME --loop -- notify-send "triggered"
```
