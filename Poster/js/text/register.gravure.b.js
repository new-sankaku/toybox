(function (PF) {
'use strict';

// TODO: 各項目は目標件数に未達。agent の session limit 復帰後に追記する。
Object.assign(PF.GENRE_TEXT.gravure.patterns, {
  title: [
    '{feelingWord}', '{feelingWord}', '{colorSeason}メモリー', '{colorSeason}デイズ',
    '{callWord}', '{season}の{place}で', 'はじめての{noun}', '{emotion}{tail}',
    '{place}／{emotion}距離', '{adj}{tail}、ふたりきり', '{noun}のとなりで',
    '{season}、{place}。', '{emotion}{noun}', '{place}、{n:days}', '{adj}{noun}、解禁。',
    '{feelingWord}な{n:days}', '{colorSeason}の{tail}', '{season}の{feelingWord}',
    '{place}の{feelingWord}', '{feelingWord}と{feelingWord}', '{callWord}、{place}へ',
    '{n:age}、{feelingWord}', '{n:age}の{tail}', '{feelingWord}／{place}',
    '{emotion}{feelingWord}', '{adj}{feelingWord}', '{feelingWord}のとなりで',
    '{feelingWord}、{n:days}', '{colorSeason}、{n:days}', '{season}の{colorSeason}',
    'ふたりの{feelingWord}', 'はじめての{feelingWord}', 'とっておきの{feelingWord}',
    '{place}でみつけた{feelingWord}', '{feelingWord}をあなたに', '{feelingWord}のつづき',
    '{callWord}っていったら', '{callWord}のあとで', '{callWord}、そのまえに',
    '{season}、{feelingWord}のひ', '{place}、{feelingWord}のじかん',
    '{colorSeason}にとけて', '{colorSeason}のむこう', '{colorSeason}をきみと',
    '{emotion}{place}', '{adj}{place}', '{place}の{n:days}', '{place}まで{n:days}',
    '{noun}と、{feelingWord}', '{tail}と、{feelingWord}', '{feelingWord}という名の{tail}',
    '{feelingWord}、はじめました', '{feelingWord}、つづけています', '{feelingWord}、みつけました',
    '{season}かぎりの{feelingWord}', '{n:days}だけの{feelingWord}', 'いまだけの{feelingWord}',
    '{place}にて、{feelingWord}', '{colorSeason}、そして{feelingWord}',
    '{feelingWord}のかけら', '{feelingWord}のとちゅう', '{feelingWord}のはじまり',
    '{feelingWord}のおわりに', '{feelingWord}をもういちど', 'もういちど{feelingWord}',
    '{emotion}{n:days}', '{adj}{n:days}', '{season}の{n:days}',
    '{place}、{colorSeason}', '{place}、{callWord}', '{feelingWord}、{callWord}'
  ],
  sub: [
    '{place}ロケ　{n:days}の撮影記録',
    '{emotion}表情を追いかけた最新作',
    '{season}の{place}で、撮り下ろし',
    '{n:age}、{emotion}{tail}',
    '{place}での{n:days}を、まるごと収録',
    '{feelingWord}の瞬間だけを集めました',
    '{colorSeason}の光のなかで',
    '{n:days}かけて撮りためた{feelingWord}',
    '{place}と{place}、ふたつの舞台で',
    '{emotion}表情から{emotion}表情まで',
    '朝から夜まで、{place}のすべてを',
    '{season}のいちばんいい時間に',
    '本人セレクトの{feelingWord}カット収録',
    '{place}ロケ、全編撮り下ろし',
    'カメラが追いかけた{n:days}の記録'
  ],
  tag: [
    '{formatMark}', '{labelName} presents', '{formatMark}／{formatMark}',
    '1st イメージ{formatMark}', 'IMAGE VIDEO',
    '{labelName}', '{formatMark} 版', 'イメージ{formatMark}', '{labelName} 作品',
    'PHOTO & MOVIE', 'IMAGE COLLECTION', 'SUMMER COLLECTION',
    '{formatMark}　{n:minutes}', '{labelName}／{formatMark}', '2nd イメージ{formatMark}',
    '3rd イメージ{formatMark}', '{formatMark} 同時発売', 'デジタル配信同時',
    '{labelName} オリジナル', 'オリジナル{formatMark}'
  ],
  badge: [
    '{bonus}', '{bonus}／{bonus}', '初回限定 {bonus}',
    '生写真{n:sheets}封入', 'ブックレット（{n:pages}）付',
    '未公開シーン{n:bonusMinutes} 追加収録', 'メイキング映像 {n:bonusMinutes}収録',
    '特典映像{n:bonusMinutes}収録', '本編{n:minutes}＋特典{n:bonusMinutes}',
    'ポストカード{n:sheets}枚付', '{bonus} 同梱', '{bonus} 封入',
    '初回盤のみ {bonus}', '数量限定 {bonus}', '早期予約特典 {bonus}',
    'デジタル特典付', '応募券封入', '複製サイン入り', 'イベント優先申込券付',
    '撮影日記{n:pages}付', 'ピンナップ{n:sheets}枚付', '特製ケース仕様'
  ],
  release: [
    '収録時間 {n:minutes}　{n:date}発売　税込 {n:price}',
    '本編{n:minutes}＋特典映像{n:bonusMinutes}　{n:date}発売',
    '{n:minutes}／{n:date}／税込 {n:price}',
    '{n:date}発売　税込 {n:price}　{n:minutes}',
    '{n:minutes}　{n:date}発売　{n:price}（税込）',
    '{n:date}　{n:minutes}　税込 {n:price}　{n:code}',
    '収録時間 {n:minutes}／{n:date}／{n:price}（税込）／{n:code}',
    '{n:date} 発売　本編{n:minutes}　税込 {n:price}',
    '本編{n:minutes}＋特典{n:bonusMinutes}／{n:date}／税込 {n:price}',
    '{n:code}　{n:minutes}　{n:date}発売　税込 {n:price}',
    '{n:minutes}収録　{n:date}リリース　{n:price}（税込）',
    '{n:date}発売　{n:minutes}　税込 {n:price}'
  ],
  credit: [
    '発売元 {labelName}',
    '企画・制作 {labelName}',
    '企画・制作 {labelName}／撮影 {person}',
    '発売元 {labelName}／販売元 {labelName}',
    '制作 {labelName}　撮影 {person}　編集 {person}',
    '{labelName}　撮影 {person}',
    '企画 {labelName}／構成 {person}／撮影 {person}',
    '出演 {person}　制作 {labelName}'
  ],
  extra: [
    '{labelName}', '{formatMark}', '{bonus}', '{labelName}／{formatMark}',
    '{n:code}', '{labelName}　{n:code}', '{formatMark}　{n:code}',
    '{labelName} presents', '{bonus}付', '{formatMark} 同時発売'
  ]
});

Object.assign(PF.GENRE_TEXT.gravure.register, {
  nominal: [
    '{emotion}{n:days}', 'はじめての{place}', '{season}の{place}、ふたりきり',
    '{place}での{n:days}', '{emotion}笑顔と、{emotion}まなざし', '素足と、潮風と、{place}',
    'カメラの前の{n:few}時間', '{season}、いちばん近い距離', '{place}へ、ふたりで',
    'はじめての{season}、はじめての表情',
    '{place}、はじめての{n:days}', '{emotion}朝と、{emotion}夕暮れ', '素足のままの{n:few}時間',
    '{season}、{place}、ふたりきり', '水着と、麦わらと、{place}',
    '{feelingWord}と、{feelingWord}', '{colorSeason}の{n:days}', '{place}の{feelingWord}',
    '{n:age}の{season}', '{n:days}ぶんの{feelingWord}', 'カメラだけが見た{n:few}時間',
    '朝の{place}、夜の{place}', '{emotion}時間の、そのぜんぶ',
    '{feelingWord}のかけらを集めて', '{place}で過ごした{n:days}',
    '{season}の光と、{emotion}表情', 'いちばん近い{n:few}センチ',
    '{place}、{colorSeason}、{feelingWord}', '{n:sheets}枚ぶんの{feelingWord}',
    '{emotion}瞬間だけを{n:minutes}'
  ],
  scale: [
    '待望の最新作', '完全撮り下ろし', 'いままででいちばん', '本人も驚いた出来ばえ',
    'ファン待望の一本', '撮り下ろし{n:few}カット追加',
    '撮り下ろし{n:count}カット', '{n:days}かけて撮影', '本人立ち会いのもと編集',
    '過去最長の収録時間', 'ファン投票で決まった衣装',
    '全編{place}ロケ', '本編{n:minutes}の完全収録',
    '{n:days}間の密着撮影', '衣装{n:few}着を撮り下ろし', 'カット数は過去最多',
    '朝から夜までノーカット', '本人セレクトで構成', 'スタッフ厳選の{n:sheets}枚',
    '未公開カットを{n:bonusMinutes}追加', '{n:count}通りの表情を収録'
  ]
});

})(window.PF = window.PF || {});
