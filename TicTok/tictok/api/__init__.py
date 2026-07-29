"""HTTP層。``tictok.server`` が組み立てるapplicationの部品置き場。

層は下から順に:

1. ``runtime``     process全体で1つしかない物(Storage・設定・manager・録画dir)
2. ``files``       録画1行から実体(path・素材・mp4・尺)を引く
3. ``fsfacts``     filesystemから引いた事実のcacheと一括取得
4. ``disk``        容量・空き・退避・保持policyの計算
5. ``media_jobs``  映像jobの永続queueとjob本体
6. ``startup`` (lifespanと起動時処理) / ``routes.*`` (各router)

参照は必ず下向き。上の層を呼びたくなったら、それは層の切り方が違うという合図である
(唯一の例外だった「queueがjob本体を呼ぶ」は、queueをjob本体と同じmoduleへ置いて解いた)。

module間の参照は ``from ... import name`` で束ねず、``module.name`` と呼び出し時に引く。
束ねると ``monkeypatch.setattr(module, "name", ...)`` が自分のbindingへ届かず、testの
差し替えが黙って素通りする(=本物が走り、たまたま同じ結果になれば緑のまま何も検証しない)。
"""
