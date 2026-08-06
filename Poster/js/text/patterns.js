export const PATTERNS = {
  cinema: {
    title: [
      '{noun}', '{adj}{tail}', '{noun}の{tail}', 'さよなら、{noun}', '{noun}に{verb}ない',
      '{season}の{noun}', '{noun}、ふたたび', '{head}と{noun}', '{noun}／{tail}',
      '{noun}は{verb}ない', '{n:chapter}　{noun}', '{noun} －{tail}－'
    ],
    sub: [
      '{noun}をめぐる{adj}{tail}の記録',
      '{place}を舞台に描く、{adj}{tail}',
      '{n:year}、{place}。すべてはそこで起きた',
      '原作 {person}『{adj}{tail}』（{studioWord}書房刊）'
    ],
    cast: [
      '{person}　{person}　{person}',
      '{person}　{person}　{person}　{person}',
      '{person}　{person}／{person}',
      '{person}　{person}　{person}　{person}　{person}'
    ],
    tag: [
      '{latinTag}', '{latinTag} / {person.en}', '{latinTag} — {n:year}',
      '興行収入 {n:boxOffice}突破', '動員 {n:admission}突破', '世界{n:countries} 公開決定'
    ],
    badge: [
      '{n:festivalNo} {festival}国際映画祭 正式出品',
      '{festival}国際映画祭 {n:sections}受賞',
      '{festival}国際映画祭 {n:sections}ノミネート',
      '全米初登場No.1',
      '{n:week}興行収入第一位',
      '世界{n:countries}で公開決定'
    ],
    release: [
      '{n:date}全国ロードショー',
      '{n:date}より全国{n:screens}にて公開',
      '{n:year}{n:date}　全国順次公開',
      '{n:date}　劇場へ'
    ],
    recommend: [
      '「{quote}」\n――{person}（{recommendRole}）',
      '「{quote}」――{person}（{recommendRole}）'
    ],
    extra: [
      '{latinTag}', '{studioWord}ピクチャーズ 配給', '{ratingMark}',
      '{studioWord}ピクチャーズ｜{ratingMark}'
    ]
  },

  gravure: {
    title: [
      '{noun}', '{season}の{place}で', 'はじめての{noun}', '{emotion}{tail}',
      '{place}／{emotion}距離', '{adj}{tail}、ふたりきり', '{noun}のとなりで',
      '{season}、{place}。', '{emotion}{noun}', '{place}、{n:days}', '{adj}{noun}、解禁。'
    ],
    sub: [
      '{place}ロケ　{n:days}の撮影記録',
      '{emotion}表情を追いかけた最新作',
      '{season}の{place}で、撮り下ろし',
      '{n:age}、{emotion}{tail}'
    ],
    tag: [
      '{formatMark}', '{labelName} presents', '{formatMark}／{formatMark}',
      '1st イメージ{formatMark}', 'IMAGE VIDEO'
    ],
    badge: [
      '{bonus}', '{bonus}／{bonus}', '初回限定 {bonus}',
      '生写真{n:sheets}封入', 'ブックレット（{n:pages}）付',
      '未公開シーン{n:bonusMinutes} 追加収録', 'メイキング映像 {n:bonusMinutes}収録'
    ],
    release: [
      '収録時間 {n:minutes}　{n:date}発売　税込 {n:price}',
      '本編{n:minutes}＋特典映像{n:bonusMinutes}　{n:date}発売',
      '{n:minutes}／{n:date}／税込 {n:price}',
      '{n:date}発売　税込 {n:price}　{n:minutes}'
    ],
    credit: [
      '発売元 {labelName}',
      '企画・制作 {labelName}',
      '企画・制作 {labelName}／撮影 {person}'
    ],
    extra: [
      '{labelName}', '{formatMark}', '{bonus}', '{labelName}／{formatMark}'
    ]
  },

  novel: {
    title: [
      '{noun}', '{noun}は{verb}ない', '{adj}{tail}', '{tail}のための{noun}',
      'ぼくが{verb}なかった理由', '{noun}と、その{tail}', '{head}、あるいは{tail}',
      '{noun}をめぐる{n:few}つの断章', '{season}の{tail}', '{person}の{tail}'
    ],
    sub: [
      '{adj}{tail}を通して{noun}を描く表題作他、珠玉の名短編{n:stories}収録',
      '{place}を舞台に描く、{adj}長編{genreWord}',
      '{n:year}、{place}。{quote}',
      '全{n:stories}収録'
    ],
    tag: ['{imprint}', '{imprint}　{n:spineCode}'],
    badge: [
      '{n:volume}突破', 'シリーズ累計{n:volume}', '{n:awardNo} {award} 受賞',
      '{award} 候補作', '{obiBoxWord}', '{obiBoxWord}／{n:volume}突破'
    ],
    credit: [
      '{person}　著',
      '{person}　著／解説＝{person}',
      '「{quote}」\n――{person}（{criticRole}）'
    ],
    release: [
      '定価：本体{n:price}＋税',
      '{imprint}　定価：本体{n:price}＋税',
      '{n:printing}　定価：本体{n:price}＋税'
    ],
    extra: [
      '{n:spineCode}', '解説＝{person}', '文庫化にあたり{n:stories}を加筆', '{imprint}'
    ]
  },

  asmr: {
    title: [
      '{noun}', '{situation}の{tail}', '{emotion}{situation}', '{adj}{tail}',
      '{situation}と{situation}', 'おやすみ、{noun}', '{situation}で{verb}なくなる夜',
      '{noun}のための{situation}', '{situation}から{situation}まで', '{tail}の{situation}'
    ],
    subtitle: [
      '{situation}と{situation}で眠る{n:minutes}',
      '{emotion}{tail}',
      '{binaural}でお届けする{situation}',
      '{trackWord}{n:few}つの{situation}',
      '眠れない夜のための{situation}',
      '{situation}、そして{situation}'
    ],
    sub: [
      '{binaural}／{n:minutes}',
      '{situation}ほか{n:track}収録',
      '{binaural}・{fileFormat}',
      '{situation}から{situation}まで'
    ],
    tag: ['{binaural}', '{binaural}／{fileFormat}', '{fileFormat}', '{binaural}／{binaural}'],
    badge: [
      '体験版あり', 'シリーズ第{n:seriesNo}作', 'track {n:trackNo}：{sceneWord}',
      '{n:files}同梱', '{situation}収録'
    ],
    credit: [
      'CV：{person}',
      'CV：{person}　シナリオ：{person}',
      'CV：{person}\nシナリオ：{person}／イラスト：{person}'
    ],
    release: [
      '総再生時間 {n:seconds}／{n:track}',
      '{n:minutes}／{n:track}',
      '総再生時間 {n:seconds}　{n:track}　{fileFormat}',
      '{n:minutes}　{n:track}　{fileFormat}'
    ],
    extra: [
      '{circleName}', '{circleName}／{fileFormat}', 'track {n:trackNo}：{sceneWord}', '{fileFormat}'
    ]
  },

  game: {
    title: [
      '{noun}', '{adj}{tail}', '{noun} －{tail}－', '{noun}：{tail}', '{head}{tail}',
      '{noun} {n:few}', '{adj}{noun}', '{noun} {n:chapter}', '{tail}の{noun}', '{adj}{noun} 完全版'
    ],
    sub: [
      '{systemWord}／{systemWord}',
      '{platform} 対応　{n:date}発売',
      '{systemWord}アクション{tail}',
      '{n:endings}の結末、{n:hours}の冒険'
    ],
    tag: ['{platform}', '{platform}／{platform}', '{platform}　{editionWord}'],
    badge: [
      '{editionWord}', '{ratingWord}', '{editionWord}／{ratingWord}',
      '{n:anniversary}周年記念エディション', 'ダウンロード版同時発売', '本編＋追加コンテンツ同梱'
    ],
    credit: [
      '発売・販売元 {publisherName}',
      '{publisherName}\n©{n:yearNo} {publisherName}',
      '開発 {publisherName}／発売 {publisherName}\n©{n:yearNo} {publisherName}'
    ],
    release: [
      '{n:date}発売　希望小売価格 {n:price}（税込）',
      '{n:date}発売　{platform}',
      '{n:year}{n:date}　{platform}',
      '{n:date}発売　ダウンロード版同時発売'
    ],
    extra: [
      'プレイ人数：{n:players}', 'オンライン対応 1〜{n:players}', 'セーブデータ数：{n:saves}',
      '{n:languages}対応', '©{n:yearNo} {publisherName}'
    ]
  },

  adult: {
    title: [
      '{attrWord}{attrWord}{noun}',
      '{attrWord}／{attrWord}／{attrWord}',
      '{adj}{noun}、{n:scenes}連発',
      '{seriesWord} 第{n:seriesNo}弾',
      '{noun}＆{tail}',
      '{noun}×{noun}×{noun}',
      '【{attrWord}】{noun}',
      '{noun}＜{attrWord}＞',
      '{attrWord}{noun}{tail}',
      '{adj}{tail}{attrWord}'
    ],
    megaSpec: [
      '{n:minutes}／全{n:scenes}／{attrWord}',
      '{n:code}／{n:minutes}／{formatWord}',
      '本編{n:minutes}＋特典{n:bonusMinutes}／{attrWord}',
      '{seriesWord}／{bonusWord}／{n:minutes}',
      '{attrWord}＋{attrWord}＋{attrWord}',
      '{n:hours}収録／{bonusWord}／{formatWord}'
    ],
    megaTail: [
      '{makerName}／{labelName}',
      '{makerName}｜{n:code}',
      '{labelName}／{seriesWord}',
      '{makerName}　{n:date}発売'
    ],
    tag: ['{seriesWord}', '{makerName}／{labelName}', '{labelName}', '{makerName}'],
    badge: ['{sashWord}'],
    release: [
      '収録時間 {n:minutes}　{n:date}発売　{n:price}（税込）',
      '本編{n:minutes}＋特典{n:bonusMinutes}　{n:date}発売',
      '{n:hours} 収録／{n:date}／{n:price}（税込）',
      '{n:minutes}／{n:date}／{n:price}（税込）'
    ],
    credit: [
      '{makerName}／{labelName}',
      '出演 {person}　{makerName}',
      '出演 {person}\n{makerName}／{labelName}'
    ],
    extra: ['{noticeWord}', '{noticeWord}／{n:code}', '{n:code}', '{formatWord}']
  }
};
