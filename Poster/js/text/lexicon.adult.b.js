(function (PF) {
'use strict';

// TODO: labelName / makerName / sashWord は目標件数に未達。
// agent の session limit 復帰後に追記する。
Object.assign(PF.GENRE_POOLS.adult, {
  labelName: [
    'ミッドナイト・ワークス', 'SILK LABEL', '蒼月企画', 'ルミナ・フィルム',
    'NOIR PICTURES', '深夜堂', 'VELVET LINE', '紫苑スタジオ', 'LATE HOUR',
    '汐見ワークス', 'NIGHT OWL', '黒森企画', 'ECLIPSE LABEL', '未明堂',
    'CRESCENT LINE', '宵闇スタジオ', 'AMBER LABEL', '夜長堂', 'INDIGO WORKS',
    '常夜企画', 'TWILIGHT LINE', '朧月スタジオ', 'OBSIDIAN LABEL', '灯影堂',
    'MIDNIGHT BLUE', '残月企画', 'SABLE LINE', '暮色スタジオ', 'ONYX LABEL',
    '夜半堂', 'DUSK WORKS', '望月企画', 'RAVEN LINE', '薄明スタジオ',
    'GARNET LABEL', '幽暗堂', 'NOCTURNE WORKS', '黒耀企画', 'SHADOW LINE',
    '深更スタジオ', 'PLUM LABEL', '暁闇堂', 'LUNAR WORKS', '夕闇企画'
  ],
  makerName: [
    '蒼月企画', '深夜堂', 'LATE HOUR', 'ミッドナイト・ワークス', 'ルミナ・フィルム',
    '紫苑スタジオ', 'NOIR PICTURES', 'VELVET LINE',
    '汐見映像', 'NIGHT OWL FILMS', '黒森映像', 'ECLIPSE PICTURES', '未明映像',
    'CRESCENT FILMS', '宵闇映像', 'AMBER PICTURES', '夜長映像', 'INDIGO FILMS',
    '常夜映像', 'TWILIGHT PICTURES', '朧月映像', 'OBSIDIAN FILMS', '灯影映像',
    'MIDNIGHT PICTURES', '残月映像', 'SABLE FILMS', '暮色映像', 'ONYX PICTURES',
    '夜半映像', 'DUSK PICTURES', '望月映像', 'RAVEN FILMS', '薄明映像',
    'GARNET PICTURES', '幽暗映像', 'NOCTURNE FILMS', '黒耀映像', 'SHADOW PICTURES',
    '深更映像', 'PLUM FILMS', '暁闇映像', 'LUNAR PICTURES', '夕闇映像'
  ],
  sashWord: [
    'ついに、ここに解禁！！', 'シリーズ最新作、登場！！', 'ついに完全版が解禁！！',
    '全{n:scenes}を一挙収録！！', '{n:hours}ぶっ通し収録！！', '祝・{n:anniversary}周年記念！！',
    '初回限定特典付きで登場！！', '待望の第{n:seriesNo}弾、始動！！', '緊急発売決定！！',
    '好評につき再入荷！！', '数量限定でお届け！！', '見逃し厳禁の一本！！',
    '在庫僅少、お早めに！！', '発売前から話題沸騰！！', '全{n:scenes}、一挙公開！！',
    'シリーズ最長{n:minutes}！！', '特典付きは今回かぎり！！', '予約受付、開始！！',
    '完全新作、ついに解禁！！', '本編{n:minutes}の大ボリューム！！', '過去最大の収録量！！',
    'シリーズ史上最多{n:scenes}！！', '待望の続編、ついに！！', '{n:date} 発売決定！！',
    '第{n:seriesNo}弾、堂々登場！！', '大好評につき増産決定！！', '限定{n:count}本のみ！！',
    '初回盤、数量限定！！', '通常版も同日発売！！', 'パッケージ限定特典あり！！',
    '配信より一足先に！！', '店舗特典、続々決定！！', '特典ディスク同梱！！',
    '完全ノーカットで収録！！', '未公開シーンを追加！！', '新装ジャケットで再登場！！',
    'シリーズ完結編、ついに！！', '総集編、ここに完成！！', '傑作選、堂々登場！！',
    '{n:minutes}の完全収録版！！', '見どころ満載の一本！！', '永久保存の決定版！！',
    'ファン待望の一本！！', '今作かぎりの仕様！！', '再販未定につきお早めに！！'
  ],
  noticeWord: [
    '本作品はフィクションです', '18歳未満の方は購入できません', '出演者は全て20歳以上です',
    '商品の仕様は予告なく変更になる場合があります', 'パッケージ写真は実物と異なる場合があります',
    '本作品に登場する人物・団体・名称等は全て架空のものです',
    '出演者の年齢は撮影時のものです',
    '特典は数量限定につき、なくなり次第終了となります',
    '収録時間には特典映像を含みます',
    '本商品の無断複製・上映・貸与・放送を禁じます',
    '掲載の価格は税込表示です',
    'ディスクの取り扱いには十分ご注意ください',
    '再生機器によっては正常に再生されない場合があります',
    '本商品は日本国内向け仕様です',
    '発売日は変更になる場合があります',
    '写真はイメージです',
    '一部の映像に乱れが生じる場合があります',
    '本作品の内容は撮影時点のものです'
  ]
});

})(window.PF = window.PF || {});
