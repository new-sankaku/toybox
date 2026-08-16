(function (PF) {
'use strict';

// TODO: 各項目は目標件数に未達。agent の session limit 復帰後に追記する。
Object.assign(PF.GENRE_TEXT.adult.patterns, {
  badge: [
    '{sashWord}', '{sashWord}', '{sashWord}',
    '{crown}{bonusWord}', '{crown}{attrWord}',
    '{bonusWord}！！', '{attrWord}！！', '{seriesWord}！！',
    '{quantityWord}収録！！', '{bonusWord}／{bonusWord}',
    '{crown} {seriesWord}', '{attrWord}＋{attrWord}',
    '{bonusWord} 同梱！！', '{formatWord}！！',
    '{crown}{quantityWord}', '{seriesWord}／{bonusWord}'
  ],
  credit: [
    '{makerName}／{labelName}',
    '出演 {person}　{makerName}',
    '出演 {person}\n{makerName}／{labelName}',
    '出演 {person}　{personAttr}',
    '{makerName}　制作',
    '企画・制作 {makerName}',
    '発売元 {makerName}／販売元 {labelName}',
    '出演 {person}／{person}　{makerName}',
    '{labelName}　{seriesWord}',
    '出演 {person}　制作 {makerName}／{labelName}',
    '{makerName}　{n:code}',
    '出演 {person}（{personAttr}）'
  ],
  release: [
    '収録時間 {n:minutes}　{n:date}発売　{n:price}（税込）',
    '本編{n:minutes}＋特典{n:bonusMinutes}　{n:date}発売',
    '{n:hours} 収録／{n:date}／{n:price}（税込）',
    '{n:minutes}／{n:date}／{n:price}（税込）',
    '{n:code}　収録時間 {n:minutes}　{n:date}発売　{n:price}（税込）',
    '品番 {n:code}／{n:minutes}／{n:date}／{n:price}（税込）',
    '{n:date}発売　{n:price}（税込）　収録時間 {n:minutes}　{n:code}',
    '収録時間 {n:minutes}　{quantityWord}　{n:date}発売　{n:price}（税込）',
    '{n:code}　{n:minutes}　{formatWord}　{n:date}発売　{n:price}（税込）',
    '本編{n:minutes}＋特典{n:bonusMinutes}／{n:date}／{n:price}（税込）／{n:code}',
    '{n:date} 発売　{n:price}（税込）　{n:code}',
    '収録時間 {n:minutes}／{quantityWord}／{n:date}発売／{n:price}（税込）',
    '{makerName}　{n:code}　{n:minutes}　{n:date}発売　{n:price}（税込）',
    '{n:minutes}　{formatWord}　{n:date}発売　{n:price}（税込）　{n:code}'
  ],
  extra: [
    '{noticeWord}', '{noticeWord}／{n:code}', '{formatWord}', '{makerName}',
    '{noticeWord}　{noticeWord}',
    '18歳未満の方への販売はいたしません',
    '{noticeWord}　{makerName}',
    '{noticeWord}／{makerName}／{n:code}',
    'この商品は18歳以上の方のみご購入いただけます',
    '{noticeWord}　{n:code}　{makerName}',
    '{noticeWord}｜{labelName}',
    '{formatWord}／{noticeWord}',
    '{quantityWord}／{noticeWord}',
    '{noticeWord}　{formatWord}　{n:code}'
  ]
});

})(window.PF = window.PF || {});
