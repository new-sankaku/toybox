export const REGISTER = {
  cinema: {
    person: 'third',
    tone: 'assertive',
    clauseA: [
      'その{season}、世界は終わる', '誰も、この結末を予想できない', '男は最後の引き金を引いた',
      '{place}に、逃げ場はない', '{adj}{tail}が、静かに崩れていく', '真実を知る者は、もういない',
      'あの日、{noun}は失われた', '{n:year}、すべての記録が消えた', '選ばれたのは、たった{n:few}人',
      '国家が、その名を消した', '{place}で、最初の犠牲者が出た', '残された時間は、あと{n:few}日',
      '彼女は、最後まで何も語らなかった', '包囲は、すでに完了している', '生き残る道は、ひとつしかない',
      '{adj}{noun}が、すべてを引き裂く', '過去は、決して赦さない', '{noun}をめぐる戦いが始まる',
      '誰かが、嘘をついている', '扉の向こうに、答えがある', '男には、帰る場所がなかった',
      'その夜、{place}は沈黙した', '約束は、血で書かれていた', '警告は、一度きりだった',
      '{tail}は、最初から仕組まれていた', '雨が、すべての痕跡を消していく',
      '正義は、いつも遅れて到着する', '{noun}を知る者から、消えていく'
    ],
    clauseB: [
      'すべては、ここから始まる', '男は、最後の選択を迫られる', '結末は、誰も知らない',
      'いま、{noun}が動き出す', '世界は、二度と元に戻らない', '{adj}{tail}だけが残る',
      '真実が、白日の下に晒される', '逃げ道は、断たれた', '代償は、あまりに大きい',
      '彼は、もう引き返さない', '答えは、{place}にある', '生きて帰る者は、いない',
      'すべての嘘が、暴かれる', '{noun}が、最後の鍵になる', '戦いは、まだ終わらない',
      '選ぶのは、彼自身だ', '時計の針は、止まらない', '運命は、すでに決まっていた',
      '誰も、彼を止められない', 'その代償を、世界が払う', '最後に立つのは、ひとりだけだ',
      '{tail}は、いま明かされる', '男は、静かに立ち上がる', '記憶が、彼を追いつめる',
      '{season}が終わるとき、すべてが終わる', '沈黙が、答えだった', 'この物語に、救いはない',
      '誰かが、代償を払わねばならない'
    ],
    connective: ['だが', 'そして', 'いま', 'やがて', 'しかし', 'そのとき', 'それでも', 'ついに', 'だからこそ', 'いまなお'],
    nominal: [
      '一発の{tail}', '最後の{n:few}日間', '{adj}{noun}、そして沈黙', '{place}、深夜{n:few}時',
      '{noun}をめぐる{n:few}日間の攻防', '{adj}{tail}の記録', '{noun}、その{tail}',
      '{season}、{place}、そして{noun}', '誰も知らない{n:few}時間', '{tail}への、最後の道',
      '{adj}{noun}という名の{tail}', '{place}発、{tail}行き'
    ],
    scale: [
      '全世界を震撼させた', '観客総立ち', '{n:week}興行収入第一位', '映画史が、書き換えられる',
      '賛否両論、しかし忘れられない', '目撃せよ', '全世界が息を呑んだ', '前作を超える衝撃',
      '実話に基づく物語', '{n:few}年の沈黙を経て', 'すべての予想を裏切る'
    ],
    forms: [
      { id: 'AB', t: '[A]。[B]。', w: 20, len: 'mid' },
      { id: 'AdashB', t: '[A]——[B]。', w: 16, len: 'mid' },
      { id: 'ACB', t: '[A]。[C]、[B]。', w: 16, len: 'long' },
      { id: 'N', t: '[N]。', w: 12, len: 'short' },
      { id: 'SN', t: '[S]。[N]。', w: 10, len: 'mid' },
      { id: 'B', t: '[B]。', w: 10, len: 'short' },
      { id: 'NdashA', t: '[N]——[A]。', w: 8, len: 'mid' },
      { id: 'SAB', t: '[S]。[A]。[B]。', w: 8, len: 'long' }
    ]
  },

  gravure: {
    person: 'first-near',
    tone: 'colloquial',
    clauseA: [
      'はじめての水着、はじめての{place}', '{n:few}日間、ずっとカメラのそばにいた',
      '{place}で、たくさん笑った', '朝いちばんの光がまぶしくて', '波の音が、ずっと聞こえていた',
      '{place}まで、電車を乗り継いで', 'ちょっとだけ、緊張しました', 'カメラの前では、素のままで',
      '{season}の風が、髪をさらっていく', '寝起きの顔も、撮られてしまった',
      '{place}の夕暮れが、きれいだった', 'アイスを{n:few}個も食べました',
      '水しぶきが、思ったより冷たくて', '{n:few}回目の撮影で、やっと慣れた',
      '麦わら帽子が、風で飛んでいった', 'はしゃぎすぎて、少し日焼けした',
      '{place}で見つけた、小さなお店', '帰りたくない、と思ってしまった', '一日中、裸足で過ごした',
      'カメラマンさんに、笑わされてばかり', '{season}の海は、まだ少し冷たい',
      '夜は、みんなで花火をしました', 'いつもより、ちょっと大人な私',
      '窓を開けたら、潮の匂いがした', '寝ころんだら、そのまま眠ってしまった',
      '{place}の朝は、鳥の声で目が覚める', 'ふたりだけの時間が、流れていく', '内緒の話も、少しだけ'
    ],
    clauseB: [
      'そのぜんぶを、収めました', '{emotion}表情を、見つけてください', 'いちばん近い距離で、どうぞ',
      'まだ誰も知らない私です', '最後まで、目が離せません', 'そんな{n:few}日間の記録です',
      'この{season}、いちばんの笑顔を', 'カメラだけが知っている表情です',
      'はじめての表情が、ここにあります', 'ぜんぶ、見ていてほしい', 'ふたりきりの時間をどうぞ',
      '素顔のままの私を', 'ずっと、そばにいてください', 'いままででいちばん、自然体で',
      'めくる手が、止まらなくなります', '{place}の光ごと、閉じ込めました', 'あとは、見てのお楽しみ',
      'その続きは、本編で', '笑った顔も、拗ねた顔も', '見たことのない私に会えます',
      'いちばん{emotion}瞬間だけを', 'まるごと、持ち帰ってください', 'そっと、となりに座るみたいに',
      'いつもより、少しだけ近く', 'この{season}の宝物になりました', 'たくさん撮ってもらいました',
      '思い出ごと、お届けします', 'どうか、最後まで'
    ],
    connective: ['そして', 'それから', 'だから', 'でも', 'そのあと', 'ちょっとだけ', 'いちばん最後に', 'いまでも', 'なんだか'],
    nominal: [
      '{emotion}{n:few}日間', 'はじめての{place}', '{season}の{place}、ふたりきり',
      '{place}での{n:few}日', '{emotion}笑顔と、{emotion}まなざし', '素足と、潮風と、{place}',
      'カメラの前の{n:few}時間', '{season}、いちばん近い距離', '{place}へ、ふたりで',
      'はじめての{season}、はじめての表情'
    ],
    scale: [
      '待望の最新作', '完全撮り下ろし', 'いままででいちばん', '本人も驚いた出来ばえ',
      'ファン待望の一本', '撮り下ろし{n:few}カット追加'
    ],
    forms: [
      { id: 'AB', t: '[A]。[B]。', w: 22, len: 'mid' },
      { id: 'ACB', t: '[A]。[C]、[B]。', w: 14, len: 'long' },
      { id: 'B', t: '[B]。', w: 14, len: 'short' },
      { id: 'N', t: '[N]。', w: 14, len: 'short' },
      { id: 'ABnote', t: '[A]。[B]♪', w: 10, len: 'mid' },
      { id: 'NN', t: '[N]／[N]', w: 8, len: 'short' },
      { id: 'SB', t: '[S]。[B]。', w: 10, len: 'mid' },
      { id: 'AdashB', t: '[A]——[B]。', w: 8, len: 'mid' }
    ]
  },

  novel: {
    person: 'literary',
    tone: 'figurative',
    clauseA: [
      '誰も信じなかった', '約束は果たされなかった', 'ぼくらは走り出した', '世界は静かに傾いた',
      '扉はひとりでに閉じた', '名前を呼ばれた気がした', '街から音が消えた', '時計は止まったままだった',
      '手紙は届かなかった', '海は昨日より遠かった', '写真の中だけが晴れていた', '嘘はやさしく響いた',
      '足跡は途中で消えていた', '電車は来なかった', '窓の外はまだ暗かった', '誰かが泣いていた',
      '答えは最初からそこにあった', '灯りはひとつずつ落ちた', '雨は三日続いた', '記録は残されていない',
      '振り返れば誰もいなかった', '夏はもう終わっていた', '合図はなかった', '地図には載っていない',
      '声だけが残った', '約束の場所は水没した', '呼吸を数えていた', '数字だけが正しかった'
    ],
    clauseB: [
      'すべてが始まる', '彼女は歩き続けた', 'ぼくは嘘をついた', '世界は動きはじめる',
      '真実は暴かれる', '誰かが待っている', '答えは風の中にある', '物語は閉じられる',
      '光は差し込んでくる', '扉は開かれる', '心は決まっていた', 'それでも朝は来る',
      '手を伸ばしてしまう', '記憶は書き換えられる', '静けさだけが残る', 'ぼくらは選んでしまった',
      '嘘はやがて本当になる', '距離は測れない', '涙は乾かない', '声は届かない',
      '約束はここから始まる', '最後の一行が反転する', '足音が近づいてくる', 'すべてを賭けるしかない',
      '世界の輪郭が変わる', '夜が明ける', '名前を思い出す', 'もう戻れない'
    ],
    connective: [
      'それでも', 'だから', 'けれど', 'そして', 'やがて', 'ただ', 'いま', 'あの日から',
      'そのとき', 'それから', 'しかし', 'いつか', 'たぶん', 'まだ', 'もう', 'ふたたび',
      'ようやく', 'ついに', 'それでもなお', 'だとしても', 'そのくせ', 'いずれ',
      'そのあいだに', 'だからこそ', 'にもかかわらず', 'ほんの少しだけ'
    ],
    nominal: [
      '{adj}{tail}をめぐる、{adj}{noun}', '{season}の{place}、そして{tail}',
      '{noun}という名の{tail}', '{adj}{noun}の、その後', '語られなかった{n:few}つの{tail}',
      '{tail}のための、{adj}{noun}', '{noun}と、その{tail}', '{adj}{tail}についての覚書',
      '{place}にまつわる{n:few}つの断章', 'ある{season}の、{adj}{tail}'
    ],
    scale: [
      '今年、いちばん静かな衝撃', '読み終えた瞬間、息ができない', '最後の一行で世界が反転する',
      '全国の書店員が泣いた', 'ページを閉じられない', '静かに、しかし確実に'
    ],
    forms: [
      { id: 'ACB', t: '[A]。[C]、[B]。', w: 22, len: 'long' },
      { id: 'AB', t: '[A]。[B]。', w: 18, len: 'mid' },
      { id: 'AdashB', t: '[A]——[B]。', w: 16, len: 'mid' },
      { id: 'N', t: '[N]。', w: 14, len: 'short' },
      { id: 'CB', t: '[C]、[B]。', w: 12, len: 'short' },
      { id: 'SA', t: '[S]。[A]。', w: 8, len: 'mid' },
      { id: 'ABC', t: '[A]。[B]。[C]、[B]。', w: 6, len: 'long' },
      { id: 'S', t: '[S]。', w: 8, len: 'short' }
    ]
  },

  asmr: {
    person: 'second',
    tone: 'address',
    clauseA: [
      '今夜は、{situation}から', '耳もとで、名前を呼びます', 'まずは、{situation}をしましょう',
      '右耳だけで囁きます', '左耳から、{situation}の音', 'おつかれさま、よく頑張りました',
      'ゆっくり、息を吸って', '眠るまで、そばにいます', '目を閉じたままでいいですよ',
      '今日は{situation}の日です', '肩の力を、抜いてください', 'そのまま、横になって',
      '{n:few}回だけ、深呼吸しましょう', '髪を、少しだけ触りますね', '毛布をかけてあげる',
      '静かな部屋に、{situation}の音だけ', 'カウントは{n:few}から始めます',
      '眠れない夜でも、大丈夫', 'ゆっくり数えてあげる', '耳を、こちらに向けてください',
      '今夜は少しだけ長く話します', 'そっと近づきますね', '{situation}の音、聞こえますか',
      '寝ころんだままで聞いてください', '声のトーンを、落としますね', 'あなたの左側にいます',
      '眠くなるまで、続けます', 'あとは、任せてください'
    ],
    clauseB: [
      'そのまま眠ってしまっていいですよ', 'おやすみなさい', '朝まで、となりにいます',
      'ゆっくり、力を抜いて', '{trackWord}{n:few}まで、続きます', '目が覚めたら、また会いましょう',
      'ここからは、囁きだけで', 'よく眠れますように', '今夜はもう、何も考えないで',
      '耳もとで、ずっと', '好きなところから聞いてください', '{binaural}でお届けします',
      'ヘッドホンで、どうぞ', '{n:minutes}、ずっとそばにいます', 'もう少しだけ、起きていて',
      'すぐに眠くなってしまいます', '呼吸に合わせて、ゆっくり', '声だけ、残しておきます',
      '眠るまで、手を離しません', 'また明日の夜に', '安心して、まかせてください',
      'いい夢を見られますように', '今夜のぶんは、これでおしまい', 'ゆっくり、まぶたを閉じて',
      'そばにいるから、大丈夫', '最後は、静かに終わります', 'この声で、眠ってください',
      'たっぷり甘やかしてあげる'
    ],
    connective: ['それから', 'そのあとは', 'つぎは', 'ゆっくりと', 'そして', 'すこしだけ', 'そのまま', 'よかったら'],
    nominal: [
      '{situation}と、{situation}', '今夜の{trackWord}は{n:few}つ', '{situation}だけの{n:minutes}',
      '耳もとの{n:minutes}', '{binaural}／{n:track}', '眠るための{situation}',
      '{situation}から、おやすみまで', '静けさと、{situation}'
    ],
    scale: [
      '{binaural}', '{binaural}／{binaural}', 'ヘッドホン推奨', '{n:track}収録',
      '{situation}・{situation}・{situation}を収録', '全編{n:minutes}'
    ],
    forms: [
      { id: 'AB', t: '[A]。[B]。', w: 22, len: 'mid' },
      { id: 'A', t: '[A]。', w: 14, len: 'short' },
      { id: 'ACB', t: '[A]。[C]、[B]。', w: 14, len: 'long' },
      { id: 'B', t: '[B]。', w: 12, len: 'short' },
      { id: 'Anote', t: '[A]♪', w: 8, len: 'short' },
      { id: 'AS', t: '[A]。[S]。', w: 12, len: 'mid' },
      { id: 'N', t: '[N]', w: 12, len: 'short' },
      { id: 'SN', t: '[S]／[N]', w: 6, len: 'mid' }
    ]
  },

  game: {
    person: 'imperative',
    tone: 'epic',
    clauseA: [
      'いま、{noun}が動き出す', '{n:few}つの{tail}、ひとつの結末', '世界は、君の選択を待っている',
      '崩壊まで、あと{n:few}日', '{adj}{tail}が、大地を覆う', 'ここから先は、誰も戻れない',
      '広大な{tail}が、いま解き放たれる', '{systemWord}で描く、新たな戦場',
      '{n:count}時間を超える冒険が待つ', '{noun}の封印が、いま解かれる', '大陸は、ふたたび燃えている',
      '君だけが、{tail}を継ぐ者だ', '{n:few}人の英雄が、いま集結する', '敵は、想像を超えてくる',
      '最果ての{tail}が、君を呼んでいる', '{systemWord}が、常識を書き換える',
      'すべての道は、{noun}へ通じる', '沈黙した{tail}が、目を覚ます', '選択が、世界の形を変える',
      '{n:few}つの陣営、終わらない戦い', '空が裂け、{noun}が降りてくる', '伝説は、ここから始まる',
      '{tail}の支配権を賭けて', '仲間は{n:few}人まで連れていける', '数千の敵が、視界を埋め尽くす',
      '{tail}の継承者は、まだ現れない', '世界の果てには、何がある', '運命は、剣の先にある'
    ],
    clauseB: [
      '選べ', 'いま、踏み出せ', '生き延びろ', 'その手で終わらせろ', '世界を、取り戻せ',
      '君の物語を始めろ', '最後まで戦い抜け', '{noun}を継承せよ', '仲間を集めろ',
      '運命に抗え', '深淵を、覗け', '伝説になれ', '道を、切り拓け', 'すべてを賭けろ',
      'この{tail}を制圧せよ', '恐れるな、進め', '君だけの結末を掴め', '限界を、超えろ',
      '大陸を駆け抜けろ', '真実を暴け', '剣を取れ', '仲間と共に立ち向かえ', '{tail}を解放せよ',
      '逃げるな', '結末は、君が決めろ', '未知へ、飛び込め', 'その目で確かめろ', '世界を、書き換えろ'
    ],
    connective: ['そして', 'いま', 'だが', 'さあ', 'ならば', 'ついに', 'すべては', 'だからこそ'],
    nominal: [
      '{systemWord}×{systemWord}', '{n:few}つの{tail}、{n:few}通りの結末',
      '{adj}{tail}、開幕', '{editionWord}、始動', '{platform}で、いま', '{noun}、覚醒',
      '{systemWord}アクション、誕生', '{n:count}時間の{tail}'
    ],
    scale: [
      'シリーズ最大volume', '{n:week}販売本数第一位', '全世界待望', '前作を超えるscale',
      '累計{n:volume}を突破したシリーズ最新作', '{editionWord}'
    ],
    forms: [
      { id: 'AB', t: '[A]。[B]。', w: 22, len: 'mid' },
      { id: 'Abang', t: '[A]——[B]！', w: 16, len: 'mid' },
      { id: 'B', t: '[B]。', w: 12, len: 'short' },
      { id: 'ACB', t: '[A]。[C]、[B]。', w: 14, len: 'long' },
      { id: 'N', t: '[N]', w: 12, len: 'short' },
      { id: 'NB', t: '[N]。[B]！', w: 10, len: 'mid' },
      { id: 'SB', t: '[S]｜[B]', w: 8, len: 'mid' },
      { id: 'ABB', t: '[A]。[B]！[B]！！', w: 6, len: 'long' }
    ]
  },

  adult: {
    person: 'none',
    tone: 'promo',
    clauseA: [
      '{bonusWord}', '{seriesWord}', '{formatWord}', '本編{n:minutes}', '{n:track}収録',
      '品番 {n:code}', '{labelName} 制作', '{n:date} 発売', '{n:week}売上第一位',
      '{n:edition} 発売中', 'パッケージ版・配信版 同時展開', '特典ディスク付',
      '収録時間 {n:minutes}', 'シリーズ累計{n:count}作', '新装ジャケット仕様',
      '通常版も同日発売', '予約受付中', 'オンライン先行公開', '本編＋特典 計{n:minutes}',
      '出演者コメント収録', '{n:few}作連続リリース', '好評につき再入荷', 'デジタル版 配信中',
      'ジャケット違い{n:few}種', '店舗特典あり', '長編{n:minutes}', '未収録カット追加', '在庫僅少'
    ],
    clauseB: [
      '見逃し厳禁', '数量限定につきお早めに', '待望の登場', 'いま、話題沸騰', 'シリーズ最高評価',
      '完全保存版', 'ファン必携の一本', '徹底収録', '永久保存の決定版', 'ついに解禁',
      '大ヒット御礼', '緊急増産', '今すぐチェック', '発売即完売', '待たせすぎた最新作',
      '全国一斉展開', '予約受付中', '特典なくなり次第終了', '文句なしの決定版', 'この一本で完結',
      'シリーズ屈指の収録量', '見どころ満載', '初回盤のみの仕様', '再販未定', 'コレクター必見',
      '圧倒的な収録量', '価格据え置き', '販売店舗限定'
    ],
    connective: ['さらに', 'しかも', 'もちろん', 'なお', 'そのうえ', '加えて'],
    nominal: [
      '{labelName}｜{seriesWord}', '{bonusWord}／{formatWord}', '{n:minutes}／{n:code}',
      '{seriesWord}｜{bonusWord}', '{formatWord}｜{n:track}', '{labelName}／{n:date}',
      '{bonusWord}｜{n:minutes}｜{n:code}', '{seriesWord}／{n:edition}'
    ],
    scale: [
      'シリーズ最長{n:minutes}', '累計{n:count}作を突破', '{n:week}売上第一位',
      '全国主要店舗で展開中', '公式配信も同時開始'
    ],
    forms: [
      { id: 'AbarB', t: '[A]｜[B]', w: 20, len: 'short' },
      { id: 'AAB', t: '[A]／[A]／[B]', w: 16, len: 'mid' },
      { id: 'AAA', t: '[A]｜[A]｜[A]', w: 14, len: 'mid' },
      { id: 'BA', t: '[B]。[A]', w: 12, len: 'short' },
      { id: 'AslashB', t: '[A]／[B]', w: 14, len: 'short' },
      { id: 'N', t: '[N]', w: 14, len: 'short' },
      { id: 'ACB', t: '[A]。[C]、[B]', w: 8, len: 'mid' },
      { id: 'SN', t: '[S]｜[N]', w: 8, len: 'mid' }
    ]
  }
};

const LEN_ORDER = { short: 0, mid: 1, long: 2 };
const PLACEHOLDER_RE = /\[([ABCNSL])\]/g;

const BANK_OF = { A: 'clauseA', B: 'clauseB', C: 'connective', N: 'nominal', S: 'scale', L: 'nominal' };

function pickFresh(rng, pool, used) {
  let v = rng.pick(pool);
  for (let i = 0; i < 5; i++) {
    if (!used[v]) { break; }
    v = rng.pick(pool);
  }
  used[v] = 1;
  return v;
}

export function buildCatchPattern(rng, genre, opts) {
  const reg = REGISTER[genre];
  if (!reg) { throw new Error('unknown genre: ' + genre); }
  const o = opts || {};
  const budget = typeof o.lenBudget === 'string' ? LEN_ORDER[o.lenBudget] : 2;
  const allowed = reg.forms.filter((f) => LEN_ORDER[f.len] <= budget);
  const pool = allowed.length > 0 ? allowed : reg.forms;
  const form = rng.weighted(pool.map((f) => ({ v: f, w: f.w })));
  const used = Object.create(null);
  let pattern = form.t.replace(PLACEHOLDER_RE, (m, key) => pickFresh(rng, reg[BANK_OF[key]], used));
  const conn = Object.keys(used).filter((k) => reg.connective.indexOf(k) >= 0)[0];
  if (conn && pattern.split(conn).length > 2) {
    pattern = form.t.replace(PLACEHOLDER_RE, (m, key) => pickFresh(rng, reg[BANK_OF[key]], Object.create(null)));
  }
  return {
    pattern: pattern,
    axes: ['register:' + reg.person, 'form:' + form.id, 'len:' + form.len]
  };
}

export function buildQuotePattern(rng, genre) {
  const reg = REGISTER[genre];
  if (!reg) { throw new Error('unknown genre: ' + genre); }
  const used = Object.create(null);
  const a = pickFresh(rng, reg.clauseA, used);
  const b = pickFresh(rng, reg.clauseB, used);
  const c = pickFresh(rng, reg.connective, used);
  const form = rng.weighted([
    { v: a + '。' + c + '、' + b + '。', w: 4 },
    { v: a + '——' + b + '。', w: 3 },
    { v: b + '。', w: 2 },
    { v: pickFresh(rng, reg.scale, used) + '。', w: 3 }
  ]);
  return form;
}
