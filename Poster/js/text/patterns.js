export const PATTERNS = {
  cinema: {
    title: [
      '{noun}', '{adj}{tail}', '{noun}の{tail}', 'さよなら、{noun}', '{noun}に{verb}ない',
      '{season}の{noun}', '{noun}、ふたたび', '{head}と{noun}', '{noun}／{tail}',
      '{person}の{tail}', '{noun}は{verb}ない', '{n:chapter}　{noun}'
    ],
    sub: [
      '{noun}をめぐる{adj}{tail}の記録',
      '{place}を舞台に描く、{adj}{tail}',
      '{n:year}、{place}。すべてはそこで起きた',
      '実話をもとに描かれた{adj}{tail}'
    ],
    tag: ['{latinTag}', '{latinTag} / {person.en}', '{latinTag} — {n:year}'],
    badge: [
      '第{n:count}回 {festival}国際映画祭 正式出品',
      '{festival}国際映画祭 {n:few}部門ノミネート',
      '{n:week}興行収入第一位',
      '{festival}映画祭 審査員特別賞'
    ],
    credit: [
      '{role} {person}',
      '{role} {person}　　{role} {person}',
      '{role} {person}　　{role} {person}\n出演 {person}　{person}　{person}',
      '{role}・{role} {person}\n出演 {person}　{person}'
    ],
    release: [
      '{n:date}全国ロードショー',
      '{n:date}公開　{n:minutes}',
      '{n:year}{n:date}　全国順次公開',
      '{n:date}より劇場公開'
    ],
    extra: ['{noun}｜{n:minutes}', '{n:code}', '{latinTag}']
  },

  gravure: {
    title: [
      '{noun}', '{season}の{place}で', 'はじめての{noun}', '{emotion}{tail}',
      '{place}／{emotion}距離', '{adj}{tail}、ふたりきり', '{noun}のとなり',
      '{season}、{place}。', '{emotion}{noun}', '{place}で{n:few}日'
    ],
    sub: [
      '{place}ロケ　{n:few}日間の撮影記録',
      '{emotion}表情を追いかけた最新作',
      '{season}の{place}で、撮り下ろし',
      'はじめてのことばかりの{n:few}日間'
    ],
    tag: ['IMAGE VIDEO', 'FIRST PHOTO BOOK', 'SPECIAL EDITION', 'BLU-RAY & DVD', 'DIGITAL EDITION', '{labelName}'],
    badge: ['{bonus}', '{bonus}／{bonus}', '{bonus}　特典{n:minutes}'],
    credit: ['{labelName}', '{labelName}／企画・制作', '撮影 {person}　{labelName}'],
    release: [
      '{n:minutes}　{n:date}発売',
      '{n:date}発売　{n:price}',
      '収録時間 {n:minutes}　{n:date}',
      '{n:date}リリース　{n:minutes}'
    ],
    extra: ['{n:code}', '{labelName}　{n:code}', '{n:price}']
  },

  novel: {
    title: [
      '{noun}', '{noun}は{verb}ない', '{adj}{tail}', '{tail}のための{noun}',
      'ぼくが{verb}なかった理由', '{noun}と、その{tail}', '{head}、あるいは{tail}',
      '{noun}をめぐる{n:few}つの断章', '{season}の{tail}', '{person}の{tail}'
    ],
    sub: [
      '{imprint}　{n:price}',
      '{award}受賞作',
      '{pushLine}',
      '長編{tail}小説'
    ],
    tag: ['{imprint}', '{imprint}／{n:edition}', '{imprint} {n:code}'],
    badge: ['{award}受賞', '{pushLine}', '{award}／{pushLine}', '{n:volume}突破'],
    credit: [
      '「{quote}」\n——{person}（{criticRole}）',
      '「{pushLine}」\n——{person}（{criticRole}）',
      '{person}　著',
      '{person}　著／解説 {person}（{criticRole}）'
    ],
    release: ['{n:price}', '{imprint}　{n:price}', '{n:date}刊行　{n:price}'],
    extra: ['{n:code}', '{imprint}', '{n:volume}突破']
  },

  asmr: {
    title: [
      '{noun}', '{situation}の{tail}', '{emotion}{situation}', '{adj}{tail}',
      '{situation}と{situation}', '{noun}／{situation}', 'おやすみ、{noun}',
      '{situation}で{verb}なくなる夜', '{n:chapter}　{situation}', '{noun}のための{situation}'
    ],
    sub: [
      '{binaural}／{n:minutes}',
      '{situation}ほか{n:track}収録',
      '{binaural}・{binaural}',
      '{situation}から{situation}まで'
    ],
    tag: ['{binaural}', 'BINAURAL SLEEP AUDIO', '{binaural}／{binaural}', 'ASMR AUDIO WORK'],
    badge: ['{situation}収録', '{situation}・{situation}収録', '{n:track}', '{binaural}'],
    credit: [
      '{voiceRole}：{person}',
      '{voiceRole}：{person}　脚本：{person}',
      '{voiceRole}：{person}\n録音・調整：{person}'
    ],
    release: ['{n:minutes}／{n:track}', '{n:date}配信開始　{n:minutes}', '{n:track}　{n:price}'],
    extra: ['{n:code}', '{binaural}', '{trackWord}{n:few}まで収録']
  },

  game: {
    title: [
      '{noun}', '{adj}{tail}', '{noun}　{n:edition}', '{head}{tail}',
      '{noun}：{tail}', '{noun} －{tail}－', '{adj}{noun}', '{noun} {n:chapter}',
      '{tail}の{noun}', '{head}戦線／{tail}'
    ],
    sub: [
      '{systemWord}／{systemWord}',
      '{platform} 対応　{n:date}発売',
      '{systemWord}アクション{tail}',
      '{n:few}つの結末、{n:count}時間の冒険'
    ],
    tag: ['{platform}', '{platform}／{platform}', '{editionWord}', '{platform} {editionWord}'],
    badge: ['{editionWord}', '{editionWord}／{n:edition}', '{n:week}販売本数第一位', '{ratingWord}'],
    credit: [
      'ディレクター {person}　音楽 {person}',
      '{systemWord}｜{systemWord}｜{systemWord}',
      'ディレクター {person}\nキャラクターデザイン {person}　音楽 {person}'
    ],
    release: [
      '{n:date}発売　{n:price}',
      '{n:year}{n:date}　{platform}',
      '{n:date}　ダウンロード版同時発売'
    ],
    extra: ['{n:code}', '{ratingWord}', '{platform}｜{ratingWord}']
  },

  adult: {
    title: [
      '{noun}', '{adj}{tail}', '{noun}の{tail}', '{season}の{noun}',
      '{noun}、{n:chapter}', '{head}と{tail}', '{adj}{noun}', '{tail}のはなし',
      '{noun}／{seriesWord}', '{place}の{tail}'
    ],
    sub: [
      '{formatWord}／{n:minutes}',
      '{seriesWord}　{bonusWord}',
      '{labelName}　{formatWord}',
      '{n:code}｜{n:minutes}｜{bonusWord}'
    ],
    tag: ['{labelName}', '{labelName}／{seriesWord}', '{labelName} {n:code}'],
    badge: ['{bonusWord}', '{bonusWord}／{bonusWord}', '{seriesWord}', '{n:week}売上第一位'],
    credit: ['出演 {person}', '出演 {person}　{person}', '出演 {person}\n企画・制作 {labelName}'],
    release: [
      '{n:date}発売　{n:minutes}',
      '{n:minutes}／{n:price}',
      '{n:date}　{formatWord}'
    ],
    extra: ['{n:code}', '{formatWord}', '{labelName}　{n:code}']
  }
};
