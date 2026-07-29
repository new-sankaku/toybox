"""routerの置き場。1 moduleに1 APIRouterで、``tictok.server`` がまとめて取り込む。

分け方は「誰が何を見に来るか」で切ってある(画面 / serverの状態 / 監視中の配信 / 配信session /
録画を読む / 成果物を作る / 容量 / 一括 / 検索 / AI / 配信者 / 全体解析 / websocket)。
route pathの前置きでは切っていない — 例えば ``/api/recordings/{id}`` は、読む側が
``recordings`` に、投入側が ``media`` に居る。同じ録画でも、壊れたときに見る場所が違うため。

routerはpathを1文字も変えない。prefixもtagも付けないのは、既存のpathと openapi.json の
operation idを動かさないためである。
"""
