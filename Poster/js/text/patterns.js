export const PATTERNS = {
  cinema: {
    title: [
      '{noun}', '{adj}{tail}', '{noun}の{tail}', 'さよなら、{noun}', '{noun}に{verb}ない',
      '{season}の{noun}', '{noun}、ふたたび', '{head}と{noun}', '{noun}／{tail}',
      '{person}の{tail}', '{noun}は{verb}ない', '{n:chapter}　{noun}'
    ],
    catch: [
      '{clauseA}。{connective}、{clauseB}。',
      '{clauseA}。{clauseB}。',
      '{connective}、{clauseB}。',
      'その{tail}は、誰にも{verb}なかった。{clauseB}。',
      '{clauseA}——{connective}、{clauseB}。',
      'あの{season}、{noun}だけが見ていた。{connective}、{clauseB}。',
      '{clauseA}。それは{adj}{tail}の話だ。',
      '{noun}に{verb}ないと、{person}は言った。{clauseB}。',
      '{clauseA}。{connective}、{noun}は残った。',
      '{adj}{tail}が、すべてを変える。{clauseB}。',
      'いま、{noun}の{tail}が明かされる。',
      '{clauseA}。{connective}、{clauseB}。それが{noun}だった。',
      '{clauseB}。{clauseA}、ただそれだけの{tail}。'
    ],
    sub: [
      '{noun}をめぐる{adj}{tail}の記録',
      '{place}を舞台に描く、{adj}{tail}',
      '{season}、{place}。{clauseA}。',
      '{n:year}、{place}。{clauseB}。'
    ],
    tag: ['{latinTag}', '{latinTag}　{person.en}', '{latinTag} — {n:year}'],
    badge: [
      '第{n:count}回 {festival}国際映画祭 正式出品',
      '{festival}国際映画祭 {n:count}部門ノミネート',
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
      '{season}、{place}。', '{emotion}{noun}', '{place}で{n:count}日'
    ],
    catch: [
      '{clauseA}。{connective}、{clauseB}。',
      '{place}で、{emotion}表情のすべてを収めた最新作。',
      'カメラの前で見せた、{emotion}素顔。{clauseB}。',
      '{place}で過ごした{n:count}日間の記録。',
      '誰も知らなかった{noun}の時間。{connective}、{clauseB}。',
      '{season}の{place}、{emotion}まなざし。',
      '{clauseA}。{emotion}{tail}が、そこにあった。',
      '{emotion}{tail}と、{adj}{tail}。',
      '{connective}、{clauseB}。{place}にて撮影。',
      '{noun}のような{n:count}日間。{clauseB}。',
      'いちばん{emotion}{tail}を、{place}で。',
      '{clauseA}。ただ、{emotion}{tail}だけが残った。'
    ],
    sub: [
      '{place}ロケ　{n:count}日間の撮影記録',
      '{emotion}{tail}を追った最新作',
      '{season}の{place}で撮り下ろし'
    ],
    tag: ['IMAGE VIDEO', 'FIRST PHOTO BOOK', 'SPECIAL EDITION', 'BLU-RAY & DVD', 'DIGITAL EDITION', '{labelName}'],
    badge: ['{bonus}', '{bonus}／{bonus}', '{bonus}　{n:edition}'],
    credit: ['{labelName}', '{labelName}／企画・制作', '撮影 {person}　{labelName}'],
    release: [
      '{n:minutes}　{n:date}発売',
      '{n:date}発売　{n:price}',
      '収録時間 {n:minutes}　{n:date}',
      '{n:date}リリース／{n:track}'
    ],
    extra: ['{n:code}', '{labelName}　{n:code}', '{n:price}']
  },

  novel: {
    title: [
      '{noun}', '{noun}は{verb}ない', '{adj}{tail}', '{tail}のための{noun}',
      'ぼくが{verb}なかった理由', '{noun}と、その{tail}', '{head}、あるいは{tail}',
      '{noun}をめぐる{n:count}の断章', '{season}の{tail}', '{person}の{tail}'
    ],
    catch: [
      '{clauseA}。{connective}、{clauseB}。',
      '{clauseA}。{clauseB}。',
      '{connective}、{clauseB}。',
      '{clauseA}——{clauseB}。',
      '{clauseA}。{connective}、{noun}は{verb}なかった。',
      '{pushLine}——{clauseB}。',
      '{pushLine}／{pushLine}',
      '{clauseA}。この{tail}は、{adj}{tail}の物語である。',
      '{award}受賞。{clauseB}。',
      '{clauseB}——{clauseA}、それだけの{tail}。',
      '{clauseA}。{connective}、{clauseB}。{pushLine}',
      '{adj}{noun}をめぐる、{adj}{tail}。'
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
      '「{clauseA}。{connective}、{clauseB}。」\n——{person}（{criticRole}）',
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
    catch: [
      '{clauseA}。{connective}、{clauseB}。',
      '{situation}から、{clauseB}。',
      '{emotion}{situation}で、{clauseB}。',
      '{connective}、{clauseB}。耳もとで、ずっと。',
      '{clauseA}。{situation}が、{tail}をほどく。',
      '{situation}・{situation}・{situation}を収録。',
      '{binaural}。{clauseB}。',
      '{clauseA}。{connective}、{situation}の音だけが残る。',
      '{adj}{tail}を、{binaural}で。',
      '眠れない夜に、{situation}と{situation}。',
      '{clauseA}。{connective}、{clauseB}。{trackWord}ごとに変わる距離。',
      '{emotion}{tail}、{n:minutes}。'
    ],
    sub: [
      '{binaural}／{n:minutes}',
      '{situation}ほか{n:track}収録',
      '{binaural}・{binaural}'
    ],
    tag: ['{binaural}', 'BINAURAL SLEEP AUDIO', '{binaural}／{binaural}', 'ASMR AUDIO WORK'],
    badge: ['{situation}収録', '{situation}・{situation}収録', '{n:track}', '{binaural}'],
    credit: [
      '{voiceRole}：{person}',
      '{voiceRole}：{person}　脚本：{person}',
      '{voiceRole}：{person}\n録音・調整：{person}'
    ],
    release: ['{n:minutes}／{n:track}', '{n:date}配信開始　{n:minutes}', '{n:track}　{n:price}'],
    extra: ['{n:code}', '{binaural}', '{trackWord}{n:count}まで収録']
  },

  game: {
    title: [
      '{noun}', '{adj}{tail}', '{noun}　{n:edition}', '{head}{tail}',
      '{noun}：{tail}', '{noun} －{tail}－', '{adj}{noun}', '{noun} {n:chapter}',
      '{tail}の{noun}', '{head}戦線／{tail}'
    ],
    catch: [
      '{clauseA}。{connective}、{clauseB}。',
      '{connective}、{clauseB}。',
      '{clauseA}。{connective}、{clauseB}。世界は君の手にある。',
      '{adj}{tail}へ、いま踏み出せ。{clauseB}。',
      '{clauseA}。選ぶのは、君だ。',
      '{systemWord}で描く{adj}{tail}。',
      '{clauseA}。{connective}、{noun}は目を覚ます。',
      '{n:count}の{tail}、ひとつの結末。{clauseB}。',
      '{clauseB}——{clauseA}、その先へ。',
      '{systemWord}×{systemWord}。{clauseB}。',
      '{clauseA}。{connective}、{clauseB}。{editionWord}',
      '果てなき{tail}が、いま起動する。'
    ],
    sub: [
      '{systemWord}／{systemWord}',
      '{platform} 対応　{n:date}発売',
      '{systemWord}アクション{tail}'
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
    catch: [
      '{clauseA}。{connective}、{clauseB}。',
      '{labelName}｜{bonusWord}｜{seriesWord}',
      '{clauseA}。{connective}、{clauseB}。{bonusWord}',
      '{seriesWord}、{bonusWord}で登場。{clauseB}。',
      '{adj}{tail}を、{formatWord}で。',
      '{clauseB}。{bonusWord}／{formatWord}',
      '{connective}、{clauseB}。{labelName}が贈る{seriesWord}。',
      '{clauseA}。それは{adj}{tail}だった。',
      '{bonusWord}｜{formatWord}｜{n:minutes}',
      '{seriesWord}。{clauseB}。',
      '{clauseA}。{connective}、{noun}だけが残った。',
      '{labelName}　{seriesWord}／{bonusWord}'
    ],
    sub: [
      '{formatWord}／{n:minutes}',
      '{seriesWord}　{bonusWord}',
      '{labelName}　{formatWord}'
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
