(function (PF) {
'use strict';

// TODO: 各項目は目標件数に未達。agent の session limit 復帰後に追記する。
Object.assign(PF.GENRE_TEXT.game.patterns, {
  sub: [
    '{systemWord}／{systemWord}',
    '{platform} 対応　{n:date}発売',
    '{systemWord}アクション{tail}',
    '{n:endings}の結末、{n:hours}の冒険',
    '{subject}を、とことん',
    '{subject}{category}、ここに登場',
    '{systemWord}で描く{subject}の世界',
    '{n:hours}を超える{tail}',
    '{subject}好きのための一本',
    'はじめてでも遊べる{subject}',
    '{scaleWord}になって帰ってきた',
    '{lifeWord}が、いま始まる',
    '{imperative}、{subject}の頂点へ',
    '{theme}の{category}、完全新作',
    '{systemWord}＋{systemWord} の融合',
    '{subtitleWord}、開幕',
    'シリーズ第{n:seriesNo}作、堂々登場',
    '{n:anniversary}周年の集大成',
    '{platform}／{platform} 同時発売',
    '{subject}の魅力を、あますところなく'
  ],
  tag: [
    '{platform}', '{platform}／{platform}', '{platform}　{editionWord}',
    '{platform} 専用', '{platform} 対応', '{platform} 版',
    '{platform}　{scaleWord}', '{platform}／デジタル版同時',
    '{platform} 独占', '{platform} 先行', '{platform}　{ratingWord}',
    '{platform}　{n:date}発売', '{platform}｜{editionWord}',
    '{platform}／{platform}／{platform}', 'MULTI PLATFORM'
  ],
  badge: [
    '{editionWord}', '{n:anniversary}周年記念エディション',
    'ダウンロード版同時発売', '本編＋追加コンテンツ同梱',
    '完全版', '特典付', 'NEW', 'LIMITED', 'HD REMASTER',
    '再入荷', '好評発売中', '大好評につき増産',
    '{scaleWord}', '{scaleWord} 版', '{editionWord} 同時発売',
    'シリーズ第{n:seriesNo}作', '{n:anniversary}周年', '完全新作',
    '追加シナリオ同梱', '設定資料集付', 'サウンドトラック付',
    '早期購入特典あり', '店舗別特典あり', '初回生産限定',
    'パッケージ版限定', '数量限定生産', '予約受付中',
    '体験版配信中', '無料アップデート対応', 'オンライン対応',
    '{subject}{category} 最新作', '{theme}の{category}', '{subtitleWord} 収録',
    'シリーズ最新作', '待望の続編', '完全リニューアル',
    '{scaleWord}で登場', '{editionWord} 好評発売中'
  ],
  credit: [
    '{publisherName}'
  ],
  release: [
    '©{n:yearNo} {publisherName}',
    '©{n:yearNo} {publisherName} ALL RIGHTS RESERVED.',
    '{n:date}発売　©{n:yearNo} {publisherName}',
    '©{n:yearNo} {publisherName}　{n:date}発売',
    '©{n:yearNo}-{n:yearNo} {publisherName}',
    '©{n:yearNo} {publisherName} All Rights Reserved.',
    '{n:date} 発売予定　©{n:yearNo} {publisherName}',
    '©{n:yearNo} {publisherName}／{publisherName}',
    '発売元 {publisherName}　©{n:yearNo}',
    '©{n:yearNo} {publisherName}　{platform} 対応',
    '好評発売中　©{n:yearNo} {publisherName}',
    '{n:date}発売予定　©{n:yearNo} {publisherName} ALL RIGHTS RESERVED.'
  ],
  extra: [
    '{editionWord}', '{latinReading}', '{scaleWord}',
    '{ratingWord}', '{subtitleWord}', '{editionWord}／{latinReading}',
    '{publisherName}', '{latinReading}　{scaleWord}',
    '{n:anniversary}周年記念', 'シリーズ第{n:seriesNo}作',
    '{editionWord} 同梱', '{subtitleWord} 収録', '{latinReading} EDITION'
  ]
});

Object.assign(PF.GENRE_TEXT.game.register, {
  connective: ['そして', 'いま', 'だが', 'さあ', 'ならば', 'ついに', 'すべては', 'だからこそ',
    'やがて', 'それでも', 'いよいよ', 'ここから', 'いざ', 'そのとき', 'こうして'],
  nominal: [
    '{systemWord}×{systemWord}', '{n:few}つの{tail}、{n:few}通りの結末',
    '{adj}{tail}、開幕', '{editionWord}、始動', '{theme}、覚醒',
    '{systemWord}アクション、誕生', '{n:hours}の{tail}',
    '{adj}{tail}、ここに開幕', '{n:few}人の英雄、{n:endings}の結末',
    '{systemWord}、新次元へ', '広がる{tail}、無限の冒険',
    '{subject}{category}、堂々完成', '{subject}の頂点へ', '{lifeWord}、はじまる',
    '{subject}と{subject}、ふたつの楽しみ', '{theme}の{category}、新章突入',
    '{subtitleWord}、ここに', '{scaleWord}、ついに登場',
    '{subject}好きのための{category}', 'やりこみ{n:hours}の{category}',
    '{systemWord}で遊ぶ{subject}', 'みんなで遊べる{subject}{category}',
    'ひとりでも、{n:few}人でも', '{n:endings}の結末、{n:hours}の物語',
    '{theme}と{theme}、交わる{tail}', '{subject}、新たなる{category}',
    '{lifeWord}と、{lifeWord}', '{subtitleWord}から{subtitleWord}へ',
    '{adj}{subject}の世界', '{platform}で、{subject}を'
  ],
  scale: [
    'シリーズ最大の物語量', '累計出荷{n:count}万本のシリーズ最新作', '{n:hours}を超える本編',
    '前作の{n:few}倍の広さ', 'シリーズ最多の{n:count}種類',
    '{n:week}販売本数第一位', '全世界待望', '前作を超える規模',
    'シリーズ最高評価', '{n:anniversary}周年の集大成', '累計{n:count}万人がプレイ',
    '本編クリアまで約{n:hours}', 'やりこみ要素{n:count}種', '収録{subject}は{n:count}種類',
    'マップは前作の{n:few}倍', '{n:endings}の結末を用意', '登場人物{n:count}名',
    '{n:few}年ぶりの完全新作', 'シリーズ初の{systemWord}', '全{n:few}章構成',
    '追加要素を{n:count}点収録', '前作の全要素を継承', 'ファン投票で選ばれた{n:count}要素'
  ]
});

})(window.PF = window.PF || {});
