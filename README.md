# claude-skills

Claude Code のスキルを配るマーケットプレイスです。プロジェクトごとにコピーせず、1 箇所を直せば全プロジェクトに届きます。

いずれのスキルもプロジェクト固有の名称・設定を含みません。

## 入れる

```sh
claude plugin marketplace add https://github.com/nanase/claude-skills.git
```

その後 `/plugin` から要るものを選びます。プロジェクトで固定するなら `.claude/settings.json` に書きます。

```json
{
  "extraKnownMarketplaces": {
    "nanase": {
      "source": { "source": "git", "url": "https://github.com/nanase/claude-skills.git" },
      "autoUpdate": true
    }
  },
  "enabledPlugins": {
    "readable@nanase": true,
    "flow@nanase": true
  }
}
```

プロジェクトを信頼した時点で登録・有効化されます。

ただし登録が走るのは信頼を尋ねる場面、つまり対話セッションだけです。`claude -p` のような非対話セッションでは `extraKnownMarketplaces` を書いていても登録されず、スキルは読み込まれません。CI で使うなら明示的に足してください。

```sh
claude plugin marketplace add https://github.com/nanase/claude-skills.git
```

## 中身

| プラグイン | スキル | 使うとき |
| --- | --- | --- |
| `readable` | readable-japanese, readable-docs, readable-skill | 文章を書く。常に要る |
| `flow` | dev-flow, requirements-define, design-proposal, convention-review, reproduce-diagnose, pr-review-loop, label-apply | GitHub で開発する |
| `ui` | visual-review | 画面がある |
| `agent-ops` | hq, handoff | 開発を子セッションへ委ねる |

呼び出しは `/flow:dev-flow` の形です。名前が衝突しなければ `/dev-flow` でも通ります。

`readable` にはコマンドが 1 つあります。`/readable:ng <語>` と打つと、その語を「使わない語」として `.claude/NG.md` に記録します。会話は止まらず、言い換えも聞かれません。readable-japanese が語彙を見るとき、このファイルを併せて参照します。

## 更新

`plugin.json` に `version` を書いていません。commit すると、その SHA が版として配られます。

ただし公式以外の marketplace は**自動更新が既定で無効**です。降ってくるようにするには、`extraKnownMarketplaces` の各エントリに `"autoUpdate": true` を書くか、`/plugin` の Marketplaces タブで有効にしてください。どちらもしない場合は、`claude plugin marketplace update nanase` を叩くまで古いままです。

## 派生先で育ったスキルを戻す

配ったスキルは、そのプロジェクトの事情を吸って育ちます。どのプロジェクトでも効く部分だけをここへ戻す手順は `.claude/skills/skill-export/` にあります。このスキルはここでしか使わないので配りません。
