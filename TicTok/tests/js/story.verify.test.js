import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { loadPage } from "./helpers/page.js";

// ストーリー画面の「検証できる作り」。縛るのは次の2つだけである。
//
// (1) **週のgift × ハイライト の対応表**(検証tab)。主語はgiftであってハイライトではない。
//     読めるべきことは4つ —— 採られたgift / **採られていないgift** / 複数に出ているgift /
//     演出区間の出なかったgift。中でも「1本も出ていない」行が消えないことが一番重要で、
//     0件を隠すと「取りこぼしが無いように見える一覧」が出来上がる。突き合わせはServerが
//     返す物をそのまま描き、画面側では組み立てない。
//
// (2) **誤りに気づける画面**。実際に事故が起きている —— 鹿の全画面演出(Guardian's Pledge /
//     4999🪙 / 視聴者C🐢💤 ｻｲｺｳｯ!)が「Goal Highlight」の名前で別人(視聴者A🐢💤)のfileへ入り、
//     出来上がったmp4を観るまで誰も気付けなかった。原因は画面がgift名とgifter名の文字列
//     しか出しておらず、**映像と突き合わせる手段が無かった**ことにある。
//
//     **確かめる手段は「表の中の小さな絵」から「同じ面の右に置いた実物の動画」へ移した。**
//     表の絵は小さすぎて中身が読めなかった(利用者の指摘)ので検証の面からは外し、代わりに
//     行を選ぶと右のplayerがその位置を映す —— 面は動かないので、数百件を続けて確かめられる。
//     絵が残っているのは**書き出す直前の最後の関門**である出力tabの下見だけで、あそこは
//     束を開いた行に2枚(ハイライト側と録画側)並べる。絵はServerが切る(画面からffmpegは
//     呼べない)ので、口が無いServerでは絵を取り下げ、取り下げた理由を名乗る —— 黙って
//     消すと、確かめる手段が無いことに誰も気付かない。
describe("story.js の検証と警告", () => {
  let page;
  let win;
  let doc;

  const STREAMER = "streamer_a";
  const URL_LIST = "/api/highlights";
  const URL_COVER = `/api/highlights/coverage?streamer=${STREAMER}`;
  const URL_MENTIONS = `/api/streamers/${STREAMER}/mentions`;
  const URL_EXPORTS = `/api/highlights/exports?streamer=${STREAMER}&week=2026-08-29`;
  const URL_DETAIL = "/api/highlights/7";
  const MEDIA_7 = "/api/highlights/7/media";
  // 2本目のハイライト。**同じgiftが複数の本に入る**ので、候補の切り替えは
  // 「別の本を開く」ところまで含めて確かめないと意味が無い。
  const MEDIA_8 = "/api/highlights/8/media";

  // 台帳。検証tabの配信者の選択肢はここから組む(走査していない配信者はハイライトを
  // 持たないので突き合わせる相手が無い)。``url`` はServerが名乗る再生URLで、右のplayerも
  // 出力tabの ▶ もこれしか見ない(画面はpathからURLを組み立てない)。
  const HIGHLIGHTS = [
    {
      id: 7, unique_id: STREAMER, filename: "g65hl0000001.mp4", path: "/hl/g65hl0000001.mp4",
      url: MEDIA_7,
      duration_seconds: 60.8, status: "matched", segment_count: 10, gift_count: 10,
      top_diamonds: 6000, total_diamonds: 20585, matched_at: 1756700000,
      // 素材の週。**Serverが名乗る**(当たったgiftのeventの時刻から決まる)。出力tabは
      // これだけを見て素材を決めるので、無ければどの週の素材にもならない。
      week: "2026-08-29", week_label: "8/29(土) 7:00 〜 9/5(土) 7:00",
      weeks: ["2026-08-29"],
    },
  ];

  // Serverの既定値。**照合側と出力側に分かれて返る**(どちらにも min_diamonds が在り、
  // 意味が違うため)。画面がこれを平らなdictとして読んでいたのが今回のbugである。
  // ``days`` は **null** で、代わりに ``day_stages`` が来る。候補の窓は1つに決まらず、
  // 狭い順に試して当たらなければ広げるためである。
  const DEFAULTS = {
    match: { days: null, day_stages: [14, 30], scope: "gift", gift_lead: 6, gift_tail: 2,
             min_diamonds: 98, window: 5, hop: 0.128 },
    export: { order: "diamonds", pad_lead: 0.3, pad_tail: 0.5, min_diamonds: 1000 },
  };

  function hit(over = {}) {
    const row = {
      highlight_id: 7, filename: "g65hl0000001.mp4", segment_id: 101, idx: 3,
      // ``at`` は**そのgiftがハイライトの中で何秒目か**で、gift演出の頭(segment_start)とは
      // 別の値である(giftはgift演出の頭に在るとは限らない)。
      at: 14.5, segment_start: 12.0, segment_end: 21.0,
      recording_id: 1153, media_start: 1736.35,
      votes: 1336, ratio: 267, corr: 0.98, confidence: "high",
      // 点(0〜100)はServerが出す。**画面は目盛りを持たない** —— 線ちょうどが50で、
      // 50を割ることと confidence が "high" でないことは同じ意味である。
      score: 96, score_weakest: "corr",
      effect: [[13.6, 19.4]], has_effect: true,
      // gift演出の中のgift 1行のid。**gift演出は複数のgiftを持つ**ので、右の手直しはこのidで
      // 相手を決める(代表を勝手に選ぶと表の行と直す相手が食い違う)。
      gift_row_id: 9101,
      inside: true, is_primary: true, manual: false,
      // 人がこのgiftの当たりとして選んだ1本か。**既定は誰も選んでいない**で、そのとき
      // 代表を決めるのは機械の順位である。
      chosen: false,
      approved: true, edited: false,
      excluded: false, segment_excluded: false, gift_excluded: false,
      // そのgift演出に載っているgifterの人数。1より大きい行が「相席」で、区間はgiftごとに
      // 持てるが、gift演出ごと外すと相手の見せ場まで消える。
      segment_gifters: 1,
      // 映像が切り替わり終わる秒と、それを測ったかどうか。**測っていないこと**と
      // **測って決まらなかったこと**は別で、画面の言うことが変わる。既定は「未測定」
      // (この列より前に照合した素材と同じ状態)。
      video_start: null, video_probed: false,
      // そのgiftの見せ場。**空は「そのgift演出を割っていない」**で、gift演出の窓と同じという
      // 意味ではない。値が在る行は、他人の演出を1frameも含まない自分の窓を持っている。
      show_start: null, show_end: null,
      ...over,
    };
    // **このgiftを切り出す範囲。** Serverは触っていないgiftにも必ず値を入れて返し、
    // そのときはgift演出の窓と同じ値になる(``cut_own`` が偽)。fixtureでも同じ形にしないと、
    // 画面が「無ければgift演出の窓」を各自で組み立てる形へ戻ってしまう。
    if (row.cut_start === undefined) row.cut_start = row.segment_start;
    if (row.cut_end === undefined) row.cut_end = row.segment_end;
    if (row.cut_own === undefined) row.cut_own = false;
    return row;
  }

  function gift(over = {}) {
    const row = {
      event_id: 900, time: 1756500000, label: "08/30 23:15",
      gift_id: 5655, gift_name: "Goal Highlight", gift_count: 1, diamonds: 6000,
      gift_image: "/api/gift-icon/5655", identity_key: "k1",
      user_nickname: "視聴者A🐢💤", user_unique_id: "viewer_a", week_diamonds: 13543,
      target: true, hits: [hit()],
      ...over,
    };
    // **1個あたりの単価。** Serverは必ず入れて返す(下限を判定しているのは合計ではなく
    // こちら)。畳んだ連投の🪙欄は「単価×件数」をこれで組む。
    if (row.unit_diamonds === undefined) row.unit_diamonds = row.diamonds / row.gift_count;
    return row;
  }

  // 4つの読みどころが1つずつ出る最小の週。**週合計(week_diamonds)は人ごとに別の値**に
  // してある —— 「Gifterごと」の並びは人の塊を週合計の多い順に置くので、全員同じ額だと
  // その規則が確かめられない。
  const ITEMS = [
    // 採られたgift(確からしさ「高」)。
    gift(),
    // **採られていないgift。** 高額なのにハイライトに1本も無い —— この面の一番の用途。
    gift({ event_id: 901, gift_name: "Fantastic Fly Love", diamonds: 19999,
           user_nickname: "視聴者C🐢💤 ｻｲｺｳｯ!", identity_key: "k2", week_diamonds: 30000,
           hits: [] }),
    // 2本のハイライトに出ているgift(重複排除の確認)。
    gift({ event_id: 902, gift_name: "Future City", diamonds: 4000, identity_key: "k3",
           user_nickname: "視聴者B🐢💤", week_diamonds: 8000,
           hits: [hit({ segment_id: 201, at: 28.0, segment_start: 27.0, segment_end: 30.0,
                       gift_row_id: 9201 }),
                  hit({ highlight_id: 8, filename: "g65hl0000005.mp4",
                        segment_id: 202, at: 4.0, segment_start: 3.0, segment_end: 9.0,
                        gift_row_id: 9202 })] }),
    // 演出区間の出なかったgift。
    gift({ event_id: 903, gift_name: "Swan", diamonds: 699, identity_key: "k4",
           user_nickname: "視聴者E🐾", week_diamonds: 5000,
           hits: [hit({ segment_id: 301, at: 36.5, segment_start: 30.0, segment_end: 42.0,
                        gift_row_id: 9301, effect: [], has_effect: false })] }),
    // **言い切れていない当たり。** 位置がずれている可能性がある行で、別人のgiftが別人の
    // fileへ入る事故はここから始まる。
    gift({ event_id: 904, gift_name: "Guardian's Pledge", diamonds: 4999, identity_key: "k5",
           user_nickname: "視聴者C🐢💤 ｻｲｺｳｯ!", week_diamonds: 20000,
           hits: [hit({ segment_id: 401, at: 47.2, segment_start: 45.0, segment_end: 54.0,
                        gift_row_id: 9401,
                        confidence: "low", corr: 0.41, score: 41,
                        approved: false })] }),
    // 塊の末尾に来る人のgift。**週合計はどの人も下限(1,000🪙)以上にしてある** ——
    // 届かない人のgiftはServerが並べないので、応答に混ぜると在り得ない画面を試すことに
    // なる。
    gift({ event_id: 905, gift_name: "Hearts", diamonds: 199, identity_key: "k6",
           user_nickname: "視聴者D🐢💤", week_diamonds: 1000 }),
    // 同じ人(k1)の2件め。**連投ではない**(giftが違う)ので塊の罫では繋がないが、
    // 「Gifterごと」の並びでは1件めの隣に来なければならない。
    gift({ event_id: 906, time: 1756500500, gift_id: 5602, gift_name: "Rosa",
           diamonds: 500, identity_key: "k1", user_nickname: "視聴者A🐢💤",
           user_unique_id: "viewer_a", week_diamonds: 13543,
           hits: [hit({ segment_id: 601, at: 24.0, segment_start: 22.0, segment_end: 27.0,
                        gift_row_id: 9601 })] }),
    // **連投。** 同じ人が同じgiftを続けて投げたもので、message_idの違う別eventである。
    // 畳むと「3件で900🪙」が「300🪙」に見えるので、3行のまま並べる。
    gift({ event_id: 910, time: 1756501000, gift_id: 7001, gift_name: "Rose",
           diamonds: 300, identity_key: "k9", user_nickname: "れんとう",
           week_diamonds: 1100,
           hits: [hit({ segment_id: 501, at: 55.0, segment_start: 54.0,
                        segment_end: 60.0, gift_row_id: 9501 })] }),
    gift({ event_id: 911, time: 1756501001, gift_id: 7001, gift_name: "Rose",
           diamonds: 300, identity_key: "k9", user_nickname: "れんとう",
           week_diamonds: 1100,
           hits: [hit({ segment_id: 501, at: 55.1, segment_start: 54.0,
                        segment_end: 60.0, gift_row_id: 9502 })] }),
    gift({ event_id: 912, time: 1756501002, gift_id: 7001, gift_name: "Rose",
           diamonds: 300, identity_key: "k9", user_nickname: "れんとう",
           week_diamonds: 1100,
           hits: [hit({ segment_id: 501, at: 55.2, segment_start: 54.0,
                        segment_end: 60.0, gift_row_id: 9503 })] }),
    // **相席。** 1つのgift演出に別人のgiftが2件載っている形で、実測ではこれが多数派に近い
    // (gift 49件のうち19件が、別のgifterと同じgift演出に載っていた)。gift演出の窓を「その行の
    // 区間」としていた頃は、片方の行で詰めた値がもう片方のfileまで動かしていた。
    gift({ event_id: 920, time: 1756502000, gift_id: 8001, gift_name: "Lion",
           diamonds: 150, identity_key: "k1", user_nickname: "視聴者A🐢💤",
           user_unique_id: "viewer_a", week_diamonds: 13543,
           hits: [hit({ segment_id: 701, at: 65.5, segment_start: 64.0,
                        segment_end: 70.0, gift_row_id: 9701, segment_gifters: 2 })] }),
    gift({ event_id: 921, time: 1756502001, gift_id: 8002, gift_name: "Heart Me",
           diamonds: 99, identity_key: "k4", user_nickname: "視聴者E🐾",
           user_unique_id: "aocha", week_diamonds: 5000,
           hits: [hit({ segment_id: 701, at: 68.5, segment_start: 64.0,
                        segment_end: 70.0, gift_row_id: 9702, segment_gifters: 2,
                        is_primary: false })] }),
    // **1人しか投げていないのに長い。** 繋ぎを跨いで2場面が1つになった疑いが濃い形で、
    // 実物(hl18 / 11.68〜22.25秒 / gifterは視聴者A1人)がこれだった。長いこと自体は
    // 正しいことがある(gifterが複数居る長い演出は、演出が続けて起きただけ)ので、
    // 条件は「長い」ではなく**「長いのに投げた人が1人」**である。
    gift({ event_id: 930, time: 1756503000, gift_id: 9001, gift_name: "Ramune",
           diamonds: 200, identity_key: "k7", user_nickname: "まぐろ",
           user_unique_id: "maguro", week_diamonds: 3000,
           hits: [hit({ segment_id: 801, at: 21.0, segment_start: 20.0,
                        segment_end: 31.0, gift_row_id: 9801 })] }),
  ];

  // 畳んだあとの行数。**ITEMS の件数とは一致しない** —— 同じgift演出へ落ちた連投
  // (Rose 3件)は1行へ畳まれる。
  const ROW_COUNT = ITEMS.length - 2;

  const COVERAGE = {
    streamer: STREAMER, week: "2026-08-29", prev_week: "2026-08-22", next_week: "",
    start_label: "8/29(土) 7:00", end_label: "9/5(土) 7:00",
    post_label: "8/29 〜 9/5", post_min: 1000, min_diamonds: 98,
    // 線は**Serverが名乗る**。画面に数字を書くと、照合側で線を動かした日に画面だけが
    // 古い線で警告を出す(min_diamonds と同じ規則)。
    long_segment_seconds: 10, score_pass: 50,
    weeks: [{ key: "2026-08-22", label: "8/22", diamonds: 30000, gifts: 400 },
            { key: "2026-08-29", label: "8/29", diamonds: 35896, gifts: 508 }],
    dropped_weeks: 0,
    totals: {
      gifts: 9, matched: 7, hits: 5, diamonds: 35896, matched_diamonds: 15698,
      gifters: 6, target_gifters: 5, offtarget: 12,
      highlights: 2, segments: 41, unidentified: 4,
    },
    items: ITEMS,
  };

  // ハイライト 1本の中身(GET /api/highlights/{id})。**右の動画エリアはこれで組む** ——
  // 行を選ぶとこの応答のgift演出から相手を引き当て、区間の手直しもこのgift演出へ当てる。
  // gift演出は ``gifts`` を持つ(1つのgift演出に複数のgiftが乗る。連投のgift演出501がその形)。
  function segGift(over = {}) {
    return {
      id: 9101, gift_event_id: 900, gift_id: 5655, gift_name: "Goal Highlight",
      gift_image: "/api/gift-icon/5655", diamonds: 6000,
      user_nickname: "視聴者A🐢💤", user_unique_id: "viewer_a",
      at: 14.5, inside: true, is_primary: true, manual: false,
      excluded: false, dropped: false, chosen: false,
      ...over,
    };
  }

  function segment(over = {}) {
    const seg = {
      id: 101, idx: 0, start: 12.0, end: 21.0, at: 14.5,
      recording_id: 1153, media_start: 1736.35,
      confidence: "high", corr: 0.98, votes: 1336, ratio: 267,
      effect: [[13.6, 19.4]], approved: true, edited: false, excluded: false, memo: "",
      video_start: null, video_probed: false,
      gifts: [segGift()],
      ...over,
    };
    seg.primary = (seg.gifts || []).find((g) => g.is_primary) || null;
    // giftごとの切り出し範囲。触っていなければ**既定の窓**がServerから返る ―― 頭は
    // gift演出の頭ではなく「映像が切り替わり終わる秒」で、測れていなければgift演出の頭になる。
    (seg.gifts || []).forEach((g) => {
      if (g.cut_start === undefined) {
        g.cut_start = seg.video_start === null || seg.video_start === undefined
          ? seg.start : seg.video_start;
      }
      if (g.cut_end === undefined) g.cut_end = seg.end;
      if (g.cut_own === undefined) g.cut_own = false;
    });
    return seg;
  }

  const SEGMENTS = [
    segment(),
    segment({ id: 601, idx: 1, start: 22.0, end: 27.0, at: 24.0,
              gifts: [segGift({ id: 9601, gift_event_id: 906, gift_id: 5602,
                                gift_name: "Rosa", diamonds: 500, at: 24.0 })] }),
    segment({ id: 201, idx: 2, start: 27.0, end: 30.0, at: 28.0,
              gifts: [segGift({ id: 9201, gift_event_id: 902, gift_id: 4001,
                                gift_name: "Future City", diamonds: 4000,
                                user_nickname: "視聴者B🐢💤", user_unique_id: "onyanko",
                                at: 28.0 })] }),
    segment({ id: 301, idx: 3, start: 30.0, end: 42.0, at: 36.5, effect: [],
              gifts: [segGift({ id: 9301, gift_event_id: 903, gift_id: 3001,
                                gift_name: "Swan", diamonds: 699,
                                user_nickname: "視聴者E🐾", user_unique_id: "aocha",
                                at: 36.5 })] }),
    // 言い切れていないgift演出。**鹿が映っているのに「Goal Highlight」と名乗ったgift演出は、
    // これと同じ形をしていた。**
    segment({ id: 401, idx: 4, start: 45.0, end: 54.0, at: 47.2, recording_id: 1143,
              confidence: "low", corr: 0.41, votes: 300, ratio: 2.0,
              effect: [], approved: false,
              gifts: [segGift({ id: 9401, gift_event_id: 904, gift_id: 1,
                                gift_name: "Guardian's Pledge", diamonds: 4999,
                                user_nickname: "視聴者C🐢💤 ｻｲｺｳｯ!", user_unique_id: "viewer_c",
                                at: 47.2 })] }),
    // 連投が1つのgift演出に乗った形。gift 3件でgift演出は1つである。
    segment({ id: 501, idx: 5, start: 54.0, end: 60.0, at: 55.0, effect: [],
              gifts: [
                segGift({ id: 9501, gift_event_id: 910, gift_id: 7001, gift_name: "Rose",
                          diamonds: 300, user_nickname: "れんとう",
                          user_unique_id: "rentou", at: 55.0 }),
                segGift({ id: 9502, gift_event_id: 911, gift_id: 7001, gift_name: "Rose",
                          diamonds: 300, user_nickname: "れんとう",
                          user_unique_id: "rentou", at: 55.1, is_primary: false }),
                segGift({ id: 9503, gift_event_id: 912, gift_id: 7001, gift_name: "Rose",
                          diamonds: 300, user_nickname: "れんとう",
                          user_unique_id: "rentou", at: 55.2, is_primary: false }),
              ] }),
    // **相席のgift演出。** 6秒に別人が2人載っている(実測の形)。区間はgiftごとに持てるので
    // 片方を詰めても相手は動かないが、gift演出ごと外すと相手の見せ場まで消える。
    segment({ id: 701, idx: 6, start: 64.0, end: 70.0, at: 65.5, effect: [],
              gifts: [
                segGift({ id: 9701, gift_event_id: 920, gift_id: 8001, gift_name: "Lion",
                          diamonds: 150, user_nickname: "視聴者A🐢💤",
                          user_unique_id: "viewer_a", at: 65.5 }),
                segGift({ id: 9702, gift_event_id: 921, gift_id: 8002,
                          gift_name: "Heart Me", diamonds: 99,
                          user_nickname: "視聴者E🐾", user_unique_id: "aocha",
                          at: 68.5, is_primary: false }),
              ] }),
  ];

  const DETAIL = { highlight: HIGHLIGHTS[0], segments: SEGMENTS };

  // 出力tabの週。配信者画面の「週のGifter」と同じ口から引く。
  const MENTIONS = {
    streamer: STREAMER, week: "2026-08-29", prev_week: "2026-08-22", next_week: "",
    start_label: "8/29(土) 7:00", end_label: "9/5(土) 7:00", post_min: 1000,
    weeks: [{ key: "2026-08-22", label: "8/22", diamonds: 30000 },
            { key: "2026-08-29", label: "8/29", diamonds: 35896 }],
    items: [],
  };

  // 置き場に実在する書き出し済みfile。**下見(plan)とは別物**で、計画を組まなくても観られる。
  const EXPORT_FILE = "260829-260905_coin13543_視聴者A🐢💤_story.mp4";
  const EXPORTS = {
    streamer: STREAMER, week: "2026-08-29", exists: true,
    directory: "D:/rec/streamer_a/LiveHightlite_マージ済み",
    items: [
      { filename: EXPORT_FILE, path: `D:/rec/streamer_a/LiveHightlite_マージ済み/${EXPORT_FILE}`,
        bytes: 12_345_678, modified_at: 1756700000,
        url: "/api/clips/file?root=work&name=streamer_a%2F1.mp4",
        week: "260829-260905", coin: 13543, position: 1, nickname: "視聴者A🐢💤",
        verified: true, provenance: true },
      { filename: "260829-260905_coin7000_視聴者C🐢💤 ｻｲｺｳｯ!_story.mp4",
        path: "D:/rec/streamer_a/LiveHightlite_マージ済み/2.mp4",
        bytes: 6_000_000, modified_at: 1756700100,
        url: "/api/clips/file?root=work&name=streamer_a%2F2.mp4",
        week: "260829-260905", coin: 7000, position: 2, nickname: "視聴者C🐢💤 ｻｲｺｳｯ!",
        verified: false, provenance: false },
    ],
  };

  // 書き出したfileの**繋いだ窓の並び**。素性のJSONにしか残っていないので、一覧とは
  // 別の口で1本ぶんだけ引く。章の帯はこれを描く。
  const URL_PROVENANCE = "/api/highlights/exports/provenance?streamer="
    + `${STREAMER}&filename=${encodeURIComponent(EXPORT_FILE)}`;
  const PROVENANCE = {
    streamer: STREAMER, filename: EXPORT_FILE, provenance: true, verified: true,
    week: "2026-08-29", nickname: "視聴者A🐢💤", seconds: 18.0,
    cuts: [
      { index: 0, at: 0.0, seconds: 9.0, highlight_id: 7, src: "g65hl0000001.mp4",
        diamonds: 6000, start: 12.0, end: 21.0,
        gifts: [{ gift_event_id: 900, gift_name: "Goal Highlight", diamonds: 6000,
                  user_nickname: "視聴者A🐢💤" }] },
      { index: 1, at: 9.0, seconds: 9.0, highlight_id: 7, src: "g65hl0000001.mp4",
        diamonds: 4999, start: 45.0, end: 54.0,
        gifts: [{ gift_event_id: 904, gift_name: "Guardian's Pledge", diamonds: 4999,
                  user_nickname: "視聴者C🐢💤 ｻｲｺｳｯ!" }] },
    ],
  };

  // 配信者ごとの投入先。**Serverが名乗る値**で、画面はpathを組み立てない —— 置き場の
  // 決まりが変わった日に、画面だけが実在しない場所を名乗る(投入は成功するので、名乗りが
  // 嘘であることに誰も気付かない)。
  const UPLOAD_DIR = "D:/rec/streamer_a/highlights";

  function routes(over = {}) {
    return {
      [`GET ${URL_LIST}`]: { items: HIGHLIGHTS, defaults: DEFAULTS,
                             upload_dirs: { [STREAMER]: UPLOAD_DIR } },
      [`GET ${URL_COVER}`]: COVERAGE,
      [`GET ${URL_COVER}&week=2026-08-22`]: { ...COVERAGE, week: "2026-08-22" },
      [`GET ${URL_DETAIL}`]: DETAIL,
      [`GET ${URL_MENTIONS}`]: MENTIONS,
      [`GET ${URL_EXPORTS}`]: EXPORTS,
      [`GET ${URL_PROVENANCE}`]: PROVENANCE,
      ...over,
    };
  }

  // jsdom の <video> は読み込みを持たないので readyState が 0 のまま、currentTime の
  // 代入も落ちる。画面側は「読み込めていない動画へは飛ばない」を守っているだけなので、
  // 飛び先を見たい test では読み込み済みの動画に見せる。
  function playableVideo(win_) {
    let at = 0;
    Object.defineProperty(win_.HTMLMediaElement.prototype, "readyState",
      { get: () => 3, configurable: true });
    Object.defineProperty(win_.HTMLMediaElement.prototype, "currentTime",
      { get: () => at, set: (v) => { at = v; }, configurable: true });
  }

  async function open(over = {}, opts = {}) {
    page = loadPage({
      page: "story",
      routes: routes(over),
      before: opts.playable ? playableVideo : undefined,
    });
    win = page.win;
    doc = page.document;
    await page.settle();
    return page;
  }

  // 検証tabは表示された時に読み込む(showViewがrenderCoverPicksを呼ぶ)。
  async function openCover(over = {}, opts = {}) {
    await open(over, opts);
    doc.getElementById("tab-cover").click();
    await page.settle();
    return page;
  }

  const rows = (id) => Array.from(doc.querySelectorAll(`#${id} tr`));
  const cellText = (tr) => Array.from(tr.cells).map((td) => td.textContent.trim());
  const pick = (groupId, value) => {
    doc.getElementById(groupId).querySelector(`[data-value="${value}"]`).click();
  };
  const seg = (value) => pick("cv-filter", value);
  // **週を引き直した回数**。印の口(POST /api/highlights/coverage/checks)も同じ前置きを
  // 持つので、GETだけを数える —— 混ぜると、印を1つ押しただけで「引き直した」ことになる。
  const coverCalls = () =>
    page.calls.fetches.filter(
      (f) => f.method === "GET" && f.url.startsWith("/api/highlights/coverage")).length;
  // 表の外(入力欄以外)からのkey操作。document へ直に投げると ev.target が document に
  // なって closest() を持たないため、本番と同じく要素から上げる。
  const key = (name, from, over = {}) => {
    (from || doc.body).dispatchEvent(
      new win.KeyboardEvent("keydown",
        { key: name, bubbles: true, cancelable: true, ...over }));
  };
  // 区間の刻みを溜めてから送るまでの間(story.js の CUT_SEND_DELAY_MS)を待つ。
  // **実時間で待つ。** 溜める仕組みそのものがtestの相手なので、timerを差し替えて
  // 飛ばすと「溜まっているか」を確かめられなくなる。
  const settleCut = async () => {
    await new Promise((resolve) => setTimeout(resolve, 500));
    await page.settle();
  };
  const rowOf = (text) =>
    rows("cv-rows").find((tr) => tr.textContent.includes(text));
  const selectRow = async (text) => {
    rowOf(text).click();
    await page.settle();
  };

  beforeEach(() => {
    page = null;
  });

  afterEach(async () => {
    if (page) await page.close();
  });

  describe("週のgift × ハイライト の対応表", () => {
    it("週も俯瞰もこの面の応答から組む(週を別の口から引き直さない)", async () => {
      await open();
      // 出力tabは対象gifterの判定を配信者画面と揃える必要があるので mentions を引く。
      // **検証tabはそこへ足さない** —— 週の選択肢も境界も coverage 自身が返すので、
      // 2つの口から引くと棚が名乗る週と表の中身が別々に動く余地ができる。
      const mentions = () =>
        page.calls.fetches.filter((f) => f.url.includes("/mentions")).length;
      const before = mentions();
      doc.getElementById("tab-cover").click();
      await page.settle();
      expect(mentions()).toBe(before);
      expect(coverCalls()).toBe(1);

      const week = doc.getElementById("cv-week");
      expect(Array.from(week.options).map((o) => o.value))
        .toEqual(["2026-08-22", "2026-08-29"]);
      expect(week.value).toBe("2026-08-29");
      // 名乗りはServerが組んだ文字列のまま。日付から組み直すと時刻が落ち、土曜の朝が
      // どちらの週とも読める名乗りになる。
      expect(doc.getElementById("cv-week-range").textContent)
        .toBe("8/29(土) 7:00 〜 9/5(土) 7:00");
      // 誰のfileが作られる週なのかも、Serverのpost_minで名乗る(画面は数字を持たない)。
      // 週の集計はbuttonで開く(既定では畳んである)が、中身はもう組んである。
      expect(doc.getElementById("cv-stats").textContent).toContain("🪙1,000");
      // gift 1件の下限もServerが返した値で名乗る(表が何で絞られているかが読めること)。
      expect(doc.getElementById("cv-note").textContent).toContain("🪙98");
    });

    it("前回見ていたtabが検証でも、一覧が届いた時点で組み上がる", async () => {
      // tabの復元は読み込みより先に走る(showViewはloadHighlightsを待たない)。届いた
      // 時点で棚を組み直さないと、開いた瞬間の空の棚がそのまま残る。
      page = loadPage({
        page: "story",
        routes: routes(),
        before: (win_) => win_.localStorage.setItem("tictok.story.view", "cover"),
      });
      win = page.win;
      doc = page.document;
      await page.settle();
      expect(doc.getElementById("view-cover").classList.contains("hidden")).toBe(false);
      expect(doc.getElementById("cv-streamer").value).toBe(STREAMER);
      expect(rows("cv-rows").length).toBe(ROW_COUNT);
    });

    it("面は3つで、無くなった「照合結果」の保存値では開かない", async () => {
      // 1本の中だけを読む面は畳んだ。**保存値がそこを指していても復元しない** ——
      // VIEWSに無い値でshowViewを呼ぶと、どの面もhiddenのままの空白の画面になる。
      page = loadPage({
        page: "story",
        routes: routes(),
        before: (win_) => win_.localStorage.setItem("tictok.story.view", "match"),
      });
      win = page.win;
      doc = page.document;
      await page.settle();
      expect(doc.getElementById("view-list").classList.contains("hidden")).toBe(false);
      expect(doc.getElementById("tab-list").classList.contains("active")).toBe(true);
      expect(doc.getElementById("tab-match")).toBeNull();
      expect(doc.getElementById("view-match")).toBeNull();
    });

    it("1行=giftで、ハイライトに出ていない行を落とさない", async () => {
      await openCover();
      expect(rows("cv-rows").length).toBe(ROW_COUNT);
      // 並びは高額順。**この面の読みどころは「高額なのに1本も無い行」**なので、
      // 19,999🪙の未出現が一番上に来る。
      const first = cellText(rows("cv-rows")[0]);
      expect(first).toContain("19,999");
      expect(first).toContain("出ていない");
      // 「出ていない」は失敗ではなく結果。記号ではなく言葉で名乗る。
      expect(rows("cv-rows")[0].querySelector(".st-cover-none")).toBeTruthy();
    });

    it("複数のハイライトに出ているgiftは件数を名乗る", async () => {
      await openCover();
      const multi = rowOf("Future City");
      // 名乗るのは印の「複数」1箇所だけ。かつては位置の列にも「＋1」を出していたが、
      // 同じことを2箇所で言うと、右半分が短語で埋まって身元の列が押し潰される。
      expect(cellText(multi)[7]).toContain("複数");
      // どの本の何秒に出ているかは区間の列のtooltipが持つ(2本ぶん並ぶ)。
      // tooltipは秒だけで、読み方の説明は置かない。
      const where = multi.cells[4].querySelector("span").title;
      expect(where.split("\n")[0]).toBe("0:28.0");
      expect(where).toContain("0:04.0");
    });

    it("何で絞った表なのかを名乗る(gift 1件の下限と週合計の下限)", async () => {
      // **並ぶのは週合計が下限(1,000🪙)以上のgifterのgiftだけ**である(利用者の指定)。
      // 絞った規則を画面が名乗らないと、居ない人のgiftを「照合の取りこぼし」として人が
      // 追いかける先になる。数字はServerが返した値(min_diamonds / post_min)で、画面は
      // 閾値を持たない。
      await openCover();
      const note = doc.getElementById("cv-note").textContent;
      expect(note).toContain("🪙98");
      expect(note).toContain("週合計🪙1,000⬆️のgifter");
      // 落とした件数は集計が名乗る(黙って消すと、人はまず数を疑う)。
      expect(doc.getElementById("cv-stats").textContent).toContain("外したgift 12件");
      // 対象外の行はそもそも届かないので、印の描き分けも置かない。
      expect(doc.getElementById("cv-rows").textContent).not.toContain("対象外");
    });

    it("束ねたアカウントの行は、畳んだ数を名前の脇で名乗る", async () => {
      // 束ね(user_merges)の在る人は、週合計が何アカウントぶんの合計なのかを出さないと、
      // その行が下限を越えている理由を画面から辿れない(配信者画面の日ぶんと同じ名乗り)。
      const merged = {
        ...COVERAGE,
        items: COVERAGE.items.map((item, index) => (
          index === 0 ? { ...item, accounts: 2,
                          person_key: "k1", identity_key: "k2" } : item)),
      };
      await openCover({ [`GET ${URL_COVER}`]: merged });
      const chips = Array.from(doc.querySelectorAll("#cv-rows .st-merged"));
      expect(chips.length).toBe(1);
      expect(chips[0].textContent).toContain("統合 2");
      expect(chips[0].dataset.accounts).toBe("2");
    });

    it("演出区間(has_effect)は画面の判断材料に使わない", async () => {
      // 実測で判定能力が無いことが判っている —— 演出が映っていない Galaxy も、確かに
      // 花火が映っている Fireworks も、どちらも false になる。区別できない印を出すと
      // 人はそれを信じ始めるので、印も絞り込みも置かない。
      await openCover();
      expect(doc.getElementById("cv-filter").querySelector('[data-value="noeffect"]'))
        .toBeNull();
      const swan = rowOf("Swan");
      expect(cellText(swan)).not.toContain("演出なし");
      // 帯にも出さない(そもそも要注意の帯そのものを置かない)。
      expect(doc.querySelector("#view-cover .x-toolbar").textContent)
        .not.toContain("演出");
    });

    it("同じgift演出へ落ちた連投は1行に畳み、件数と合計を出す", async () => {
      // **同じ演出なら1行。** 実物は Ramune 200🪙 ×4 が0.92秒の間に届いた1回の
      // combo burst で、演出は1つ・出力にも1本しか入らない(主だけが通る)。同じ区間の
      // 行が4つ並ぶのは表の水増しで、しかも2件目以降が「出力なし」を名乗るので、別人のgiftが
      // 載っているように読めた(利用者の指摘)。
      await openCover();
      const roses = rows("cv-rows").filter((tr) => cellText(tr)[2] === "Rose");
      expect(roses.length).toBe(1);
      // **畳んでも件数と合計は消さない。** 「3件で900🪙」が「300🪙」に見えてはいけない。
      expect(roses[0].querySelector(".st-combo-n").textContent).toBe("×3");
      expect(cellText(roses[0])[1]).toContain("900");
      expect(cellText(roses[0])[1]).toContain("300×3");
      // 1行に畳んだ塊は罫でつながない(つなぐ相手の行が無い)。
      expect(roses[0].classList.contains("st-combo")).toBe(false);
      // 2件目以降が「出力なし」を名乗っていたのが誤り。この印は**別人のgiftが主**の意味である。
      expect(cellText(roses[0])[7]).not.toContain("出力なし");
      // 別人・別giftの行は塊に含めない。
      expect(rowOf("Goal Highlight").classList.contains("st-combo")).toBe(false);
    });

    it("見せ場を持つ行は出力なしにしない(自分の窓で出力に載る)", async () => {
      // TikTokは全画面演出を順番待ちで1つずつ流すので、継ぎ目の無い1続きの場面には別人の
      // 演出が何本も並ぶ。照合がそれを割れた行は自分の窓を持っており、他人の演出は窓の外で
      // ある —— 主でないという理由だけで「出力に載らない」と名乗るのは誤りになる。
      await openCover({
        [`GET ${URL_COVER}`]: {
          ...COVERAGE,
          items: ITEMS.map((g) => (g.event_id !== 921 ? g : {
            ...g,
            hits: [hit({ segment_id: 701, at: 68.5, segment_start: 64.0,
                         segment_end: 70.0, gift_row_id: 9702, segment_gifters: 2,
                         is_primary: false, show_start: 67.2, show_end: 70.0 })],
          })),
        },
      });
      const row = rowOf("Heart Me");
      expect(cellText(row)[7]).not.toContain("出力なし");
      expect(row.classList.contains("st-offtarget")).toBe(false);
    });

    it("見せ場が無い行は「出力なし」を名乗る", async () => {
      // 割る手掛かりが無いgift演出では、他人の演出が入る危険は消えていない。
      await openCover();
      const row = rowOf("Heart Me");
      expect(cellText(row)[7]).toContain("出力なし");
    });

    it("gift演出が違えば連投でも畳まない", async () => {
      // 演出が2つ在るなら、確かめる相手も2つである。畳む根拠(同じ演出)がそこには無い。
      await openCover({
        [`GET ${URL_COVER}`]: {
          ...COVERAGE,
          items: ITEMS.map((g) => (g.event_id !== 912 ? g : {
            ...g,
            hits: [hit({ segment_id: 502, at: 61.0, segment_start: 60.0,
                         segment_end: 66.0, gift_row_id: 9504 })],
          })),
        },
      });
      // 時刻順にすると塊が隣り合う。**罫でつなぐのは並びの上で隣り合う塊だけ**という
      // 規則はそのままで、件数は**eventの数**(2+1=3)で数える。
      pick("cv-order", "time");
      const roses = rows("cv-rows").filter((tr) => cellText(tr)[2] === "Rose");
      expect(roses.length).toBe(2);
      // 畳めた側は2件ぶん、畳めなかった側は1件ぶんの区間を持つ。
      expect(cellText(roses[0])[4]).toBe("0:54.0〜1:00.0");
      expect(cellText(roses[1])[4]).toBe("1:00.0〜1:06.0");
      roses.forEach((tr) => expect(tr.classList.contains("st-combo")).toBe(true));
      expect(roses[0].querySelector(".st-combo-n").textContent).toBe("×3");
    });

    it("絞り込みはServerが返した行の性質だけで行う", async () => {
      await openCover();
      const names = () => rows("cv-rows").map((tr) => tr.textContent);
      const before = page.calls.fetches.length;

      seg("missing");
      expect(rows("cv-rows").length).toBe(1);
      expect(names()[0]).toContain("Fantastic Fly Love");

      seg("multi");
      expect(rows("cv-rows").length).toBe(1);
      expect(names()[0]).toContain("Future City");

      // 言い切れていない当たりだけ。**別人のgiftが別人のfileへ入る事故の起点**を
      // その場で並べられることが要件。
      seg("risk");
      expect(rows("cv-rows").length).toBe(1);
      expect(names()[0]).toContain("Guardian's Pledge");

      seg("all");
      expect(rows("cv-rows").length).toBe(ROW_COUNT);
      // 絞り込みも並べ替えも画面の中だけで済ませる(Serverから引き直さない)。
      expect(page.calls.fetches.length).toBe(before);
    });

    it("並びに「Gifterごと」があり、人の塊を週合計の多い順に置く", async () => {
      // 1人ぶんを続けて確かめるための並び。**同じ人のgiftが離れて並ぶと、その人のfileに
      // 何が入るのかを1本ぶん通して見られない。** 塊の順は週合計(誰のfileを作るかの根拠)、
      // 塊の中は高額順である。
      await openCover();
      pick("cv-order", "gifter");
      const names = rows("cv-rows").map((tr) => cellText(tr)[2]);
      expect(names).toEqual([
        "Fantastic Fly Love",  // k2 / 週30,000
        "Guardian's Pledge",   // k5 / 週20,000
        "Goal Highlight",      // k1 / 週13,543 の高額な方
        "Rosa",                // k1 / 同じ人なので隣に来る
        "Lion",                // k1 / 同上(150🪙なので塊の末尾)
        "Future City",         // k3 / 週8,000
        "Swan",                // k4 / 週5,000
        "Heart Me",            // k4 / 同じ人なので隣に来る
        "Ramune",              // k7 / 週3,000
        "Rose",                // k9 / 週1,100(連投3件を畳んだ1行)
        "Hearts",              // k6 / 週1,000
      ]);
      // 高額順のままなら Rosa(500🪙) は Rose(畳んで900🪙)の**後ろ**へ回る —— 畳んだ行の
      // 額は合計だからである。**塊で並んでいることが、Gifterごとの並びが効いている証拠。**
      pick("cv-order", "diamonds");
      expect(rows("cv-rows").map((tr) => cellText(tr)[2])).toEqual([
        "Fantastic Fly Love", "Goal Highlight", "Guardian's Pledge", "Future City",
        "Rose", "Swan", "Rosa", "Ramune", "Hearts", "Lion", "Heart Me",
      ]);
    });

    it("NG済だけを並べられる(外した物を後から見直せる)", async () => {
      await openCover({
        [`GET ${URL_COVER}`]: {
          ...COVERAGE,
          items: ITEMS.map((g) => (g.event_id !== 903 ? g : {
            ...g, hits: g.hits.map((h) => ({ ...h, excluded: true, segment_excluded: true })),
          })),
        },
      });
      seg("ng");
      expect(rows("cv-rows").length).toBe(1);
      expect(rows("cv-rows")[0].textContent).toContain("Swan");
      expect(rows("cv-rows")[0].classList.contains("st-excluded")).toBe(true);
    });

    it("言い切れていない当たりは行ごと目立たせ、スコアの列でも名乗る", async () => {
      // **鹿の全画面演出が「Goal Highlight」の名前で別人のfileへ入った事故は、この行から
      // 始まっていた。** gift演出の表はもう無く、この列と行の印が唯一の手掛かりである ——
      // 印を見て右の動画を確かめるのが、画面から事故に気付ける道筋そのもの。
      await openCover();
      const risky = rowOf("Guardian's Pledge");
      expect(risky.classList.contains("st-risk")).toBe(true);
      // **語ではなく数を出す**(利用者の指定) —— 「高 / 低」の2択では、低い行が10件
      // 並んだときにどれから観ればよいのかを語が答えられなかった。
      expect(cellText(risky)[5]).toBe("41");
      // tooltipは元になった3つの値だけ。読み方の説明は置かない。
      expect(risky.querySelector(".st-risk-text").title)
        .toBe("票 1,336 / 比 267.0 / 相関 0.41");
      // 確かめた印は**確かめた行にだけ**付く。まだの行には何も付かない —— 始めた時点では
      // 全部がまだなので、印にすると全ての行の末尾に同じ語が並ぶだけになる。
      expect(cellText(risky)[7]).not.toContain("確認済");

      // 言い切れている当たりには印を付けない —— 普通の結果に警告を出すと、印そのものが
      // 読まれなくなる。
      const sure = rowOf("Goal Highlight");
      expect(sure.classList.contains("st-risk")).toBe(false);
      expect(cellText(sure)[5]).toBe("96");
      // 線に届いている行には色を付けない —— 普通の結果に警告を出すと、色が読まれなくなる。
      expect(sure.querySelector(".st-risk-text")).toBeNull();
      // どのハイライトにも出ていない行も「要注意」ではない。**当たりが無いのは
      // 「位置がずれているかもしれない」とは別の話**で、混ぜると両方が読めなくなる。
      expect(rows("cv-rows")[0].classList.contains("st-risk")).toBe(false);
      expect(cellText(rows("cv-rows")[0])[5]).toBe("—");
    });

    it("1人しか投げていないのに長いgift演出は警告の列で名乗る", async () => {
      // **照合そのものが壊れている疑い**だけを出す列である。印(次の列)は「知っておく
      // こと」なので、混ぜると普通に付く印に紛れて見落とす。実物(hl18)は11.68〜22.25秒の
      // 1件で、中に繋ぎのワイプが在り、2場面が1つになっていた。
      await openCover();
      const warned = rowOf("Ramune");
      expect(cellText(warned)[6]).toContain("11.0秒");
      expect(warned.querySelector(".st-warn-text")).toBeTruthy();
      // **「長い」だけでは警告しない。** gifterが複数居る長いgift演出は、演出が続けて
      // 起きただけである。
      expect(cellText(rowOf("Goal Highlight"))[6]).toBe("—");
      expect(cellText(rowOf("Rose"))[6]).toBe("—");
    });

    it("線はServerが名乗った値で判じる(画面に数字を書かない)", async () => {
      // 画面が線を持つと、照合側で動かした日に画面だけが古い線で警告を出す。
      await openCover({
        [`GET ${URL_COVER}`]: { ...COVERAGE, long_segment_seconds: 20 },
      });
      expect(cellText(rowOf("Ramune"))[6]).toBe("—");
      // Serverが名乗らなければ、警告そのものを出さない(推測で線を作らない)。
      await openCover({
        [`GET ${URL_COVER}`]: { ...COVERAGE, long_segment_seconds: undefined },
      });
      expect(cellText(rowOf("Ramune"))[6]).toBe("—");
    });

    it("Serverが点を名乗らない行は「—」で、線に届いた行と同じ見え方にしない", async () => {
      await openCover({
        [`GET ${URL_COVER}`]: {
          ...COVERAGE,
          items: ITEMS.map((g) => (g.event_id !== 900 ? g : {
            ...g, hits: g.hits.map((h) => ({ ...h, score: undefined })),
          })),
        },
      });
      expect(cellText(rowOf("Goal Highlight"))[5]).toBe("—");
    });

    it("要注意は帯で説明せず、表の列で読ませる", async () => {
      // 「⚠ ハイライトに出ていないgift 88件（演出を持つ階層 88件 / 最高 🪙6,599）」の
      // ような文章の帯は置かない(利用者の指定) —— 同じことが表の列に出ており、件数は
      // 絞り込みを押したときの表の長さそのものである。
      await openCover();
      expect(doc.getElementById("cv-warn")).toBeNull();
      expect(doc.getElementById("cv-summary")).toBeNull();
      // 出ていないgiftは「区間」の列がそう名乗る。
      const missing = rows("cv-rows")[0];
      expect(cellText(missing)[4]).toContain("出ていない");
      // 言い切れていない当たりは「スコア」の列と行の印で読める。
      const risky = rows("cv-rows").find((tr) => tr.classList.contains("st-risk"));
      expect(risky).toBeTruthy();
      expect(Number(cellText(risky)[5])).toBeLessThan(COVERAGE.score_pass);
      // 絞り込みを押せば、その行だけが並ぶ。
      seg("missing");
      expect(rows("cv-rows").length).toBe(1);
    });

    it("俯瞰の割合はServerが返した合計から出す", async () => {
      await openCover();
      const stats = () => Array.from(doc.querySelectorAll("#cv-stats .st-stat")).map((el) => [
        el.querySelector(".st-stat-l").textContent,
        el.querySelector(".st-stat-v").textContent,
        el.querySelector(".st-stat-n") ? el.querySelector(".st-stat-n").textContent : "",
      ]);
      const of = (label) => stats().find(([l]) => l === label);
      // 割合はServerが返した合計(totals)から出す。行を数え直すと、絞るたびに動いて
      // 意味を失う。
      expect(of("週のgift")[1]).toBe("9件");           // totals.gifts
      expect(of("週のgift")[2]).toBe("（→ 7件（77.8%））"); // matched / gifts
      // **「うち◯◯」は親と同じ行に置く。** 帯として横へ流れるので、独立した行にすると
      // 何の内訳なのか読めない場所へ飛ぶ。
      expect(of("gift演出")[2]).toBe("（未同定 4件）");
      // 絞り込みを掛けても俯瞰は動かない。
      seg("missing");
      expect(of("週のgift")[2]).toBe("（→ 7件（77.8%））");
    });

    it("取得できなかったときに0件として描かない", async () => {
      await openCover({
        [`GET ${URL_COVER}`]: () =>
          new win.Response(JSON.stringify({ detail: "落ちました" }), { status: 500 }),
      });
      // この面は「無いgift」を読む面なので、失敗を空の表として出すと「全部ハイライトに
      // 無い」と読める。
      expect(rows("cv-rows").length).toBe(0);
      const empty = doc.getElementById("cv-empty");
      expect(empty.classList.contains("list-failed")).toBe(true);
      expect(empty.classList.contains("hidden")).toBe(false);
      // 前の週の数字も名乗りも残さない。棚だけが前の週を名乗り続けると、その週を
      // 見ているように読める。
      expect(doc.getElementById("cv-stats").textContent).toBe("");
      expect(doc.getElementById("cv-week-range").textContent).toBe("");
      expect(doc.getElementById("cv-week").options.length).toBe(0);
    });
  });

  // 表と動画を同じ面に置いたことが、この画面の作り直しの中身そのものである。以前は行を
  // clickすると「照合結果」tabへ飛ばされていて、1件確かめるたびに面が入れ替わるので
  // 数百件を続けて見ることができなかった。
  describe("行を選ぶと右の動画がそこを映す(面は動かない)", () => {
    it("行clickでそのハイライトのその位置を映す(giftの位置を優先する)", async () => {
      await openCover({}, { playable: true });
      await selectRow("Guardian's Pledge");
      // **面は動かない。** 選んだだけでtabが入れ替わるなら、続けて確かめられない。
      expect(doc.getElementById("view-cover").classList.contains("hidden")).toBe(false);
      expect(doc.getElementById("tab-cover").classList.contains("active")).toBe(true);
      expect(doc.getElementById("tab-list").classList.contains("active")).toBe(false);
      expect(doc.getElementById("tab-export").classList.contains("active")).toBe(false);
      // 動画はServerが名乗った再生URL(画面はpathから組み立てない)。
      const video = doc.getElementById("cv-video");
      expect(video.getAttribute("src")).toBe(MEDIA_7);
      // 飛び先はgiftそのものの位置(at=47.2)。gift演出の頭(45.0)ではない ——
      // 演出はgiftの地点から立ち上がるので、頭では中身が判らない。
      expect(video.currentTime).toBeCloseTo(47.2, 3);
      // 触る相手は**選んだ行のgiftそのもの**で、印もその行に付く。以前は動画の下に
      // 「切り出す範囲」の枠が開いて同じ値をもう一度映していたが、範囲を動かす受け皿は
      // 時間軸の側にあり、名乗りは行の印で足りる(利用者の指定で枠を外した)。
      expect(rowOf("Guardian's Pledge").classList.contains("st-current")).toBe(true);
      expect(cellText(rowOf("Guardian's Pledge"))[4]).toBe("0:45.0〜0:54.0");
    });

    it("同じ本の別の行へ移っても、動画を読み込み直さない", async () => {
      // srcを差し替えるたびに読み込みからやり直しになり、続けて見られない。
      await openCover({}, { playable: true });
      await selectRow("Goal Highlight");
      const before = page.calls.fetches.filter((f) => f.url === URL_DETAIL).length;
      await selectRow("Swan");
      expect(page.calls.fetches.filter((f) => f.url === URL_DETAIL).length).toBe(before);
      expect(doc.getElementById("cv-video").currentTime).toBeCloseTo(36.5, 3);
    });

    it("出ていない行はclickしても映せない(飛び先が無い)", async () => {
      await openCover({}, { playable: true });
      const missing = rows("cv-rows")[0];
      expect(missing.classList.contains("row-clickable")).toBe(false);
      // 「出ていない」は区間の列が名乗る。行のtooltipで言い直さない。
      expect(missing.querySelector(".st-cover-none")).toBeTruthy();
      // key操作では選べてしまうので、**何が起きているのかを言葉で名乗る** —— 前の行の
      // 映像が出たままだと、それがこの行の中身だと読まれる。
      key("ArrowDown");
      await page.settle();
      expect(doc.getElementById("cv-play-status").textContent).toBe("出ていない");
    });

    it("↑↓(j/k)で次の行へ送れ、入力欄の中では効かない", async () => {
      // **数百件を続けて確かめるための道具。** 1件ずつclickして目で追う作りだと、
      // 現実的に見切れない。
      await openCover({}, { playable: true });
      const current = () => rows("cv-rows").findIndex((tr) =>
        tr.classList.contains("st-current"));
      expect(current()).toBe(-1);

      key("ArrowDown");
      await page.settle();
      expect(current()).toBe(0);
      key("j");
      await page.settle();
      expect(current()).toBe(1);
      expect(rows("cv-rows")[1].textContent).toContain("Goal Highlight");
      key("ArrowUp");
      await page.settle();
      expect(current()).toBe(0);
      key("k");
      await page.settle();
      // 先頭より上へは行かない(押しっぱなしで選択が外れない)。
      expect(current()).toBe(0);

      // 入力欄の中では効かせない。打鍵がそのまま操作になると、🪙の下限を打っている
      // 途中で行が送られる。
      key("j", doc.getElementById("cv-min"));
      await page.settle();
      expect(current()).toBe(0);
    });

    it("行を選んでも週は引き直さない(選ぶたびに表が組み直されない)", async () => {
      await openCover({}, { playable: true });
      const before = coverCalls();
      await selectRow("Goal Highlight");
      await selectRow("Swan");
      expect(coverCalls()).toBe(before);
    });
  });


  // **同じgiftは複数のハイライトに入る。** どれを観るかを人が選べないと、機械が代表に
  // 決めた1本にそのgiftのアニメが1frameも無いとき、その行から確かめる手が無い ——
  // 実測(Whale diving 2,150🪙 / 視聴者B🐢💤)は3本に当たり、3本とも同席と判定され、
  // 代表になった5.9秒の1本には映っておらず、11.1秒ある別の1本の11.8〜15.8秒にだけ
  // 映っていた。選ぶことは「このgiftはこの1本を使う」という指定でもある。
  describe("候補の切り替え", () => {
    const picker = () => doc.getElementById("cv-hit");
    const options = () => Array.from(picker().options).map((o) => o.textContent);
    const PATCH_8 = "PATCH /api/highlights/8/segments/202/gifts/9202";
    // 2本目のハイライト(Future Cityが当たっているもう1本)。
    const SEGMENT_202 = segment({
      id: 202, idx: 0, start: 3.0, end: 9.0, at: 4.0,
      gifts: [segGift({ id: 9202, gift_event_id: 902, gift_id: 4001,
                        gift_name: "Future City", diamonds: 4000,
                        user_nickname: "視聴者B🐢💤", user_unique_id: "onyanko",
                        at: 4.0 })],
    });
    const DETAIL_8 = {
      highlight: { id: 8, unique_id: STREAMER, filename: "g65hl0000005.mp4",
                   path: "/hl/g65hl0000005.mp4", url: MEDIA_8,
                   duration_seconds: 24.0, status: "matched", week: "2026-08-29" },
      segments: [SEGMENT_202],
    };
    const chosen = (over = {}) => ({
      segment: { ...SEGMENT_202,
                 gifts: [{ ...SEGMENT_202.gifts[0], chosen: true, ...over }] },
    });
    const withSecond = (over = {}) => ({
      "GET /api/highlights/8": DETAIL_8, [PATCH_8]: chosen(), ...over,
    });

    it("当たりが複数の行では候補が選べ、1本の行では触れない", async () => {
      await openCover(withSecond(), { playable: true });
      await selectRow("Future City");
      expect(picker().disabled).toBe(false);
      // **file名が主語。** 頭は共通の羅列なので尻だけを出し、尺と印を添える。
      expect(options()).toEqual(["…l0000001.mp4 3.0秒 (主)",
                                 "…l0000005.mp4 6.0秒 (主)"]);
      expect(picker().value).toBe("9201");

      // 1本しか当たっていない行では触らせない —— 押せる見た目のまま何も起きないのが
      // 一番読めない。
      await selectRow("Swan");
      expect(picker().disabled).toBe(true);
      expect(options()).toEqual(["…l0000001.mp4 12.0秒 (主)"]);
    });

    it("候補を選ぶとその本を開き、gift演出の頭から映す", async () => {
      await openCover(withSecond(), { playable: true });
      await selectRow("Future City");
      const video = doc.getElementById("cv-video");
      expect(video.getAttribute("src")).toBe(MEDIA_7);

      picker().value = "9202";
      picker().dispatchEvent(new win.Event("change"));
      await page.settle();

      expect(video.getAttribute("src")).toBe(MEDIA_8);
      // **giftの秒(4.0)ではなくgift演出の頭(3.0)。** アニメは順番に出るので、giftの秒に
      // 着地すると、そこで映っているのは先に投げた人のアニメである(実測でその差は5.4秒)。
      // 候補を選ぶのは「自分のアニメがどれに映っているか」を探す操作なので、頭を飛ばしては
      // 用を成さない。
      expect(video.currentTime).toBeCloseTo(3.0, 3);
    });

    it("選ぶと「この1本を使う」として送り、表の代表と印が入れ替わる", async () => {
      await openCover(withSecond(), { playable: true });
      await selectRow("Future City");
      expect(cellText(rowOf("Future City"))[4]).toBe("0:27.0〜0:30.0");

      picker().value = "9202";
      picker().dispatchEvent(new win.Event("change"));
      await page.settle();

      const sent = page.calls.fetches.find(
        (f) => f.method === "PATCH" && f.url.endsWith("/segments/202/gifts/9202"));
      expect(JSON.parse(sent.body)).toEqual({ chosen: true });
      // 表の代表が選んだ1本へ移る(区間もそちらの値になる)。**引き直さない。**
      expect(cellText(rowOf("Future City"))[4]).toBe("0:03.0〜0:09.0");
      expect(rowOf("Future City").textContent).toContain("選択");
      expect(options()[0]).toContain("(選択中)");
    });

    it("送れなかったら選び直しは無かったことにする", async () => {
      await openCover(withSecond({
        // 失敗の応答は**NodeのResponse**で作る(win.Response は接続失敗に化ける)。
        [PATCH_8]: () =>
          new Response(JSON.stringify({ detail: "壊れました" }), { status: 500 }),
      }), { playable: true });
      await selectRow("Future City");

      picker().value = "9202";
      picker().dispatchEvent(new win.Event("change"));
      await page.settle();

      // 指定できたように見せない —— selectが押した見た目のまま残ると、書けていない
      // 指定を人が「済んだ」と読む。
      expect(picker().value).toBe("9201");
      expect(rowOf("Future City").textContent).not.toContain("選択");
    });

    // **縦が行、横が候補。** ↑↓(j/k)が表の行を送り、H/Lが同じgiftの別の本を送る ――
    // 代表の1本に本人のアニメが映っていない行では、隣の本を見に行けることが確かめる
    // 唯一の手になる。selectを開く操作と同じ物なので、送るたびに「この1本を使う」も送る
    // (keyだけ「観るだけ」にすると、目で選んだ1本と書き出す1本が食い違う)。
    it("H / L でも候補を送れ、端では回り込む", async () => {
      const PATCH_7 = "PATCH /api/highlights/7/segments/201/gifts/9201";
      const back = { segment: { ...SEGMENTS[2],
                                gifts: [{ ...SEGMENTS[2].gifts[0], chosen: true }] } };
      await openCover(withSecond({ [PATCH_7]: back }), { playable: true });
      await selectRow("Future City");
      const video = doc.getElementById("cv-video");
      expect(video.getAttribute("src")).toBe(MEDIA_7);

      key("l");
      await page.settle();
      expect(picker().value).toBe("9202");
      expect(video.getAttribute("src")).toBe(MEDIA_8);
      const sent = page.calls.fetches.find(
        (f) => f.method === "PATCH" && f.url.endsWith("/segments/202/gifts/9202"));
      expect(JSON.parse(sent.body)).toEqual({ chosen: true });

      // 当たりは2〜3本なので端では回り込む(戻すkeyを覚えなくても隣へ行ける)。
      key("l");
      await page.settle();
      expect(picker().value).toBe("9201");
      key("h");
      await page.settle();
      expect(picker().value).toBe("9202");
    });

    // **人が詰めた候補へ送ったときは、詰めた範囲の頭から映す。** 候補送りが常にgift演出の
    // 頭から流すのは「自分のアニメがどの本に映っているか」を探す操作だからで、窓を自分で
    // 決め終えた行にその理由はもう無い ―― 詰めた範囲の外から流れると、出力へ入る範囲そのものを
    // 確かめられない。
    it("自分で詰めた候補へ送ると、詰めた範囲の頭から映す", async () => {
      const PATCH_7 = "PATCH /api/highlights/7/segments/201/gifts/9201";
      const back = { segment: { ...SEGMENTS[2],
                                gifts: [{ ...SEGMENTS[2].gifts[0], chosen: true }] } };
      // 詰めた後の候補B。**開き直しても詰めた窓が返る**(Serverが持っている)。
      let gift8 = { ...SEGMENT_202.gifts[0] };
      const detail8 = () => ({ ...DETAIL_8,
                               segments: [{ ...SEGMENT_202, gifts: [gift8] }] });
      await openCover(withSecond({
        "GET /api/highlights/8": () => detail8(),
        [PATCH_8]: ({ init }) => {
          const body = JSON.parse(init.body);
          gift8 = body.cut_start === undefined
            ? { ...gift8, ...body }
            : { ...gift8, cut_start: body.cut_start, cut_end: body.cut_end,
                cut_own: true };
          return { segment: { ...SEGMENT_202, gifts: [gift8] } };
        },
        [PATCH_7]: back,
      }), { playable: true });
      await selectRow("Future City");
      const video = doc.getElementById("cv-video");

      key("l");                                   // 候補B(3.0〜9.0)へ
      await page.settle();
      expect(video.getAttribute("src")).toBe(MEDIA_8);
      key("]", null, { shiftKey: true });          // 頭 +1.0(3.0 → 4.0)
      await settleCut();
      expect(gift8.cut_start).toBe(4);

      key("l");                                   // 回り込んで候補Aへ
      await page.settle();
      key("l");                                   // もう一度候補Bへ
      await page.settle();
      expect(video.getAttribute("src")).toBe(MEDIA_8);
      expect(video.currentTime).toBeCloseTo(4.0, 3);
    });

    // **詰めた直後にH/Lを押しても、溜めた刻みは送られる。** 候補を送ると開いているgift演出が
    // 入れ替わるので、送る前の値は行き先を失って黙って消える ―― 行を送る↑↓と同じ規則である。
    it("詰めた直後に候補を送っても、溜めた刻みを先に送る", async () => {
      const PATCH_7 = "PATCH /api/highlights/7/segments/201/gifts/9201";
      const back = { segment: { ...SEGMENTS[2],
                                gifts: [{ ...SEGMENTS[2].gifts[0], chosen: true }] } };
      await openCover(withSecond({ [PATCH_7]: back }), { playable: true });
      await selectRow("Future City");
      key("]", null, { shiftKey: true });          // 頭 +1.0(27.0 → 28.0)
      key("l");                                   // 送る前に候補を送る
      await settleCut();

      const sent = page.calls.fetches.filter(
        (f) => f.method === "PATCH" && f.url.endsWith("/segments/201/gifts/9201"));
      expect(sent.map((f) => JSON.parse(f.body)))
        .toEqual([{ cut_start: 28, cut_end: 30 }]);
    });

    it("当たりが1本の行では H / L で何も起きない", async () => {
      await openCover(withSecond(), { playable: true });
      await selectRow("Swan");
      const before = page.calls.fetches.length;
      key("l");
      await page.settle();
      expect(picker().value).toBe("9301");
      expect(page.calls.fetches.length).toBe(before);
    });
  });


  // 「確認済み」の印。**この面は数百件を上から順に潰していく面**なので、どこまで見たかが
  // 残らないと、開き直すたびに最初から確かめ直すことになる。印はgift 1件ごとで、gift演出の
  // ``approved`` には相乗りさせない —— **どのハイライトにも出ていない行にこそ印が要る**
  // (この面の一番の用途がそこで、その行はgift演出もgift行も持たない)。
  describe("確認済みの印", () => {
    const checkbox = (tr) => tr.querySelector("input[type=checkbox]");
    const checkCalls = () =>
      page.calls.fetches.filter((f) => f.url === "/api/highlights/coverage/checks");

    it("出ていない行にも押せて、gift 1件ごとの口へ送る", async () => {
      await openCover({ "POST /api/highlights/coverage/checks": {
        gift_event_ids: [901], checked: true } });
      // **当たりの無い行**(Fantastic Fly Love)のcheckboxを押す。
      const row = rowOf("Fantastic Fly Love");
      const box = checkbox(row);
      expect(box.disabled).toBe(false);
      expect(box.checked).toBe(false);
      const before = coverCalls();
      box.click();
      await page.settle();

      expect(checkCalls().length).toBe(1);
      expect(JSON.parse(checkCalls()[0].body))
        .toEqual({ gift_event_ids: [901], checked: true });
      // **週ぜんたいを引き直さない**(NGと同じ理由。1件ごとに組み直すと見ていた場所が飛ぶ)。
      expect(coverCalls()).toBe(before);
      expect(checkbox(rowOf("Fantastic Fly Love")).checked).toBe(true);
    });

    // **見終わった行は地を沈める。** 印がcheckboxだけだと、数百行を上から潰す面で「どこまで
    // 見たか」が行の側から読めず、右端の小さな四角を1行ずつ追うことになる。**字の濃さと
    // 太さには触らない** —— そちらは「出ている / 出ていない / 対象外」という照合の結果の軸で、
    // 混ぜると済んだ当たり行と未確認の「出ていない」行が同じ見た目になる。
    it("確認済みの行は地を沈める(当たりの無い行にも付く)", async () => {
      await openCover({ "POST /api/highlights/coverage/checks": {
        gift_event_ids: [901], checked: true } });
      const row = () => rowOf("Fantastic Fly Love");
      expect(row().classList.contains("st-checked")).toBe(false);
      checkbox(row()).click();
      await page.settle();
      expect(row().classList.contains("st-checked")).toBe(true);
      // 照合の結果の軸は残る(沈めても「出ていない」行は薄いまま)。
      expect(row().classList.contains("st-nogift")).toBe(true);
    });

    it("畳んだ行の一部だけが確認済みなら沈めない", async () => {
      // 「済」に見せると畳んだ中の未確認が消える(checkboxの indeterminate と同じ約束)。
      const marked = { ...COVERAGE,
                       items: ITEMS.map((g) => ({ ...g, checked: g.event_id === 910 })) };
      await openCover({ [`GET ${URL_COVER}`]: marked });
      expect(rowOf("Rose").classList.contains("st-checked")).toBe(false);
    });

    it("送れなかったら印は付かない(保存されていない印を付いたように見せない)", async () => {
      // 失敗の応答は**NodeのResponse**で作る。win.Response で作ると jsdom では
      // 接続失敗に化けて、status を読む経路が通らない。
      await openCover({ "POST /api/highlights/coverage/checks": () =>
        new Response(JSON.stringify({ detail: "落ちました" }), { status: 500 }) });
      checkbox(rowOf("Fantastic Fly Love")).click();
      await page.settle();
      expect(checkbox(rowOf("Fantastic Fly Love")).checked).toBe(false);
    });

    it("Aキーでも同じ口へ送る(当たりの無い行でも効く)", async () => {
      await openCover({ "POST /api/highlights/coverage/checks": {
        gift_event_ids: [901], checked: true } }, { playable: true });
      // **当たりの無い行はclickでは選べない**(映す物が無いので row-clickable が付かない)。
      // ↑↓では選べるので、そこで印を押せることがこのtestの相手である。高額順の先頭が
      // その行(19,999🪙で1本も出ていない)。
      key("ArrowDown");
      await page.settle();
      key("a");
      await page.settle();
      expect(JSON.parse(checkCalls()[0].body))
        .toEqual({ gift_event_ids: [901], checked: true });
    });

    // **Enterは印(A)と送り(↓)を1打に畳んだ物**である。数百件を上から潰す面で2つのkeyを
    // 交互に叩かせると、打鍵が倍になるうえ、どちらかを叩き忘れた行が「見たのに印が無い」
    // 「印は在るのに見ていない」として残る。
    it("Enterで確認済みにして、次のgiftを再生する", async () => {
      await openCover({ "POST /api/highlights/coverage/checks": {
        gift_event_ids: [901], checked: true } }, { playable: true });
      const video = doc.getElementById("cv-video");
      let played = 0;
      video.play = () => { played += 1; };
      key("ArrowDown");
      await page.settle();
      key("Enter");
      await page.settle();

      expect(JSON.parse(checkCalls()[0].body))
        .toEqual({ gift_event_ids: [901], checked: true });
      expect(checkbox(rowOf("Fantastic Fly Love")).checked).toBe(true);
      // 次の行(高額順の2番目)を選び、**そのgiftの位置から再生する**。
      expect(rowOf("Goal Highlight").classList.contains("st-current")).toBe(true);
      expect(played).toBe(1);
      expect(video.currentTime).toBeCloseTo(14.5, 3);
    });

    // **印は付ける側へ倒す**(Aのような切り替えにしない)。送りながら押すkeyが、既に印の
    // 在る行で印を落とすと、通り過ぎた後ろで「どこまで見たか」が静かに壊れる。
    it("Enterは既に確認済みの行でも印を落とさない", async () => {
      const marked = { ...COVERAGE,
                       items: ITEMS.map((g) => ({ ...g, checked: g.event_id === 901 })) };
      await openCover({ [`GET ${URL_COVER}`]: marked,
                        "POST /api/highlights/coverage/checks": {
                          gift_event_ids: [901], checked: true } }, { playable: true });
      key("ArrowDown");
      await page.settle();
      key("Enter");
      await page.settle();
      expect(JSON.parse(checkCalls()[0].body))
        .toEqual({ gift_event_ids: [901], checked: true });
      expect(checkbox(rowOf("Fantastic Fly Love")).checked).toBe(true);
    });

    // 送れていない行を置いて次へ移ると、印の無い行が「見た」として画面から流れ、次に
    // 開いた時に黙って戻ってくる。
    it("印を送れなかったらEnterでも行を送らない", async () => {
      await openCover({ "POST /api/highlights/coverage/checks": () =>
        new Response(JSON.stringify({ detail: "落ちました" }), { status: 500 }) },
      { playable: true });
      key("ArrowDown");
      await page.settle();
      key("Enter");
      await page.settle();
      expect(checkbox(rowOf("Fantastic Fly Love")).checked).toBe(false);
      expect(rowOf("Fantastic Fly Love").classList.contains("st-current")).toBe(true);
    });

    // 「未確認」で絞っているときは、印を付けた行がその場で表から抜ける ―― 抜けた後の
    // **同じ位置が既に次のgift**なので、そこから更に1つ送ると1件飛ばす。
    it("未確認で絞っていても、Enterで1件飛ばさない", async () => {
      await openCover({ "POST /api/highlights/coverage/checks": {
        gift_event_ids: [901], checked: true } }, { playable: true });
      seg("unchecked");
      key("ArrowDown");
      await page.settle();
      key("Enter");
      await page.settle();
      expect(rowOf("Fantastic Fly Love")).toBeUndefined();
      expect(rows("cv-rows")[0].textContent).toContain("Goal Highlight");
      expect(rows("cv-rows")[0].classList.contains("st-current")).toBe(true);
    });

    it("未確認で絞ると、印の付いていない行だけが残る", async () => {
      const marked = { ...COVERAGE,
                       items: ITEMS.map((g) => ({ ...g, checked: g.event_id === 900 })) };
      await openCover({ [`GET ${URL_COVER}`]: marked });
      // 母数は**畳んだ後の行数**から採る(連投は1行に畳まれるので、items の数とは違う)。
      const all = rows("cv-rows").length;
      seg("unchecked");
      const texts = rows("cv-rows").map((tr) => tr.textContent);
      expect(texts.length).toBe(all - 1);
      expect(texts.some((t) => t.includes("Goal Highlight"))).toBe(false);
    });

    // **畳んだ行は中のgift全部が相手である。** 代表1件だけへ送ると、畳みを解いた時に
    // 同じ塊の中へ確認済みと未確認が混ざる(印はgift event 1件ごとなので、塊は状態を
    // 持たない)。口がidをlistで受けるのはこのためである。
    it("畳んだ連投は中の全件をまとめて1回で送る", async () => {
      await openCover({ "POST /api/highlights/coverage/checks": {
        gift_event_ids: [910, 911, 912], checked: true } });
      checkbox(rowOf("Rose")).click();
      await page.settle();
      expect(checkCalls().length).toBe(1);
      expect(JSON.parse(checkCalls()[0].body))
        .toEqual({ gift_event_ids: [910, 911, 912], checked: true });
      expect(checkbox(rowOf("Rose")).checked).toBe(true);
    });

    it("畳んだ行の一部だけが確認済みなら「済」には見せない", async () => {
      // 「済」に見せると畳んだ中の未確認が消える。
      const marked = { ...COVERAGE,
                       items: ITEMS.map((g) => ({ ...g, checked: g.event_id === 910 })) };
      await openCover({ [`GET ${URL_COVER}`]: marked });
      const box = checkbox(rowOf("Rose"));
      expect(box.checked).toBe(false);
      expect(box.indeterminate).toBe(true);
    });
  });

  describe("見つけたその場で直せる", () => {
    // NGは「出力(ファイル連結)から外す」そのもの。**確からしさの低い当たりをその場で
    // 落とせること**が、この面へ動画を置いた一番の理由である。外す場所が別の面に在ると、
    // 見つけた人がそこまで辿らない。
    it("行のNGは gift 1件の口へ送る(同じgift演出の別の人を巻き添えにしない)", async () => {
      // **表の1行はgift 1件である。** 1つのgift演出には別人のgiftが複数入るので(実測でgift
      // 49件のうち19件)、gift演出の口へ送ると押した覚えのない人の見せ場まで消える。
      const patched = {
        ...SEGMENTS[4],
        gifts: [{ ...SEGMENTS[4].gifts[0], excluded: true }],
      };
      await openCover({
        "PATCH /api/highlights/7/segments/401/gifts/9401": { segment: patched },
      }, { playable: true });
      const before = coverCalls();
      rowOf("Guardian's Pledge").querySelector(".st-ngbtn").click();
      await page.settle();

      const patch = page.calls.fetches.find((f) => f.method === "PATCH");
      expect(patch.url).toBe("/api/highlights/7/segments/401/gifts/9401");
      expect(JSON.parse(patch.body)).toEqual({ excluded: true });
      // **週ぜんたいを引き直さない。** 1件外すたびに表が組み直されると、見ていた場所も
      // 選択も飛ぶ。
      expect(coverCalls()).toBe(before);
      // 表の印はその場で変わる(送った結果が画面に映らないと、直したつもりで進む)。
      const after = rowOf("Guardian's Pledge");
      expect(after.classList.contains("st-excluded")).toBe(true);
      expect(after.querySelector(".st-ngbtn").textContent).toBe("NG解除");
      // NG済で絞れば、外した行だけを見直せる。
      seg("ng");
      expect(rows("cv-rows").length).toBe(1);
      expect(rows("cv-rows")[0].textContent).toContain("Guardian's Pledge");
    });

    it("Nキーでも同じ口へ送る(行を送りながら落とせる)", async () => {
      await openCover({
        "PATCH /api/highlights/7/segments/101/gifts/9101": {
          segment: { ...SEGMENTS[0],
                     gifts: [{ ...SEGMENTS[0].gifts[0], excluded: true }] },
        },
      }, { playable: true });
      await selectRow("Goal Highlight");
      key("n");
      await page.settle();
      const patch = page.calls.fetches.find((f) => f.method === "PATCH");
      expect(patch.url).toBe("/api/highlights/7/segments/101/gifts/9101");
      expect(JSON.parse(patch.body)).toEqual({ excluded: true });
    });

    it("区間を動かすと gift の口へ頭と尻を揃えて送り、表が追随する", async () => {
      // **区間はそのまま出力に切り出される範囲である。** 直した値が表に映らないと、
      // 画面に出ている範囲と実際に繋がれる範囲が食い違ったまま書き出すことになる。
      //
      // 送り先は**giftの口**で、頭だけを動かしたときも**2つ揃えて**送る ―― 片方だけを
      // 受け付ける形にすると、頭を詰めた行が「窓を持っている」と判定されたまま尻はNULL、
      // という読み手のいない状態が作れてしまう。
      await openCover({
        "PATCH /api/highlights/7/segments/401/gifts/9401": {
          segment: { ...SEGMENTS[4],
                     gifts: [{ ...SEGMENTS[4].gifts[0],
                               cut_start: 46.0, cut_end: 54.0, cut_own: true }] },
        },
      }, { playable: true });
      await selectRow("Guardian's Pledge");
      key("]", null, { shiftKey: true });        // 頭 +1.0(45.0 → 46.0)
      await settleCut();

      const patch = page.calls.fetches.find((f) => f.method === "PATCH");
      expect(patch.url).toBe("/api/highlights/7/segments/401/gifts/9401");
      expect(JSON.parse(patch.body)).toEqual({ cut_start: 46, cut_end: 54 });
      const cells = cellText(rowOf("Guardian's Pledge"));
      expect(cells[4]).toBe("0:46.0〜0:54.0");
      // **giftの位置は動かない。** 動いたのは切り出す範囲だけで、録画の中のgiftは
      // 同じ場所に在る(gift演出の頭を動かしたときだけ位置も一緒に動く)。位置は列を持たず、
      // 区間のtooltipで名乗る —— 位置も区間も同じ形の数字なので、隣り合わせると
      // どちらがfileに入る方なのかが読めなかった。
      expect(rowOf("Guardian's Pledge").cells[4].querySelector("span").title)
        .toContain("0:47.2");
      // この行だけの区間を持ったことが読めること。gift演出の窓のままとは同じ形の数字なので、
      // 印が無いと詰めたつもりの値が実はgift演出の窓だった、という読み違いが起きる。
      expect(rowOf("Guardian's Pledge").querySelector(".st-cut-own")).toBeTruthy();
    });

    it("区間を詰めた行は、選び直すと新しい範囲の頭から観せる", async () => {
      // **詰めた後の再生が範囲に追従しないと、詰める操作の意味が無い。** 飛び先を
      // giftの位置に固定していた頃は、頭を後ろへ詰めても飛び先は古いままで、範囲の外から
      // 流れていた(直したのに直っていないように見える)。
      await openCover({
        "PATCH /api/highlights/7/segments/401/gifts/9401": {
          segment: { ...SEGMENTS[4],
                     gifts: [{ ...SEGMENTS[4].gifts[0],
                               cut_start: 49.0, cut_end: 52.0, cut_own: true }] },
        },
      }, { playable: true });
      await selectRow("Guardian's Pledge");
      const video = doc.getElementById("cv-video");
      // 触っていない行はgiftの位置(gift演出の窓は6秒手前から始まるので、頭では何も映らない)。
      expect(video.currentTime).toBeCloseTo(47.2, 3);
      key("]", null, { shiftKey: true });
      await settleCut();
      expect(cellText(rowOf("Guardian's Pledge"))[4]).toBe("0:49.0〜0:52.0");
      video.currentTime = 0;
      await selectRow("Guardian's Pledge");
      expect(video.currentTime).toBeCloseTo(49.0, 3);
    });

    it("giftより手前へ動かした区間でも、押した瞬間に止まらない", async () => {
      // 範囲ごとgiftの手前へ動かすと、giftの位置はもう終端の後ろに在る。飛び先をそこに
      // していた頃は、区間再生の見張りが最初のtimeupdateで止め、**何も再生されなかった。**
      await openCover({
        "PATCH /api/highlights/7/segments/401/gifts/9401": {
          segment: { ...SEGMENTS[4],
                     gifts: [{ ...SEGMENTS[4].gifts[0],
                               cut_start: 45.0, cut_end: 46.0, cut_own: true }] },
        },
      }, { playable: true });
      await selectRow("Guardian's Pledge");
      const video = doc.getElementById("cv-video");
      key(",", null, { shiftKey: true });
      await settleCut();
      expect(cellText(rowOf("Guardian's Pledge"))[4]).toBe("0:45.0〜0:46.0");
      video.currentTime = 0;
      await selectRow("Guardian's Pledge");
      expect(video.currentTime).toBeCloseTo(45.0, 3);
      let paused = false;
      video.pause = () => { paused = true; };
      video.dispatchEvent(new win.Event("timeupdate"));
      expect(paused).toBe(false);
    });

    it("畳んだ連投の区間を詰めると、その1行が新しい区間になる", async () => {
      // 畳んだ行が触るのは**主(is_primary)のgift**である。代表を並び順で決めると、
      // 触った値が出力に載らない行に付く(出力へ入るのは主の1件だけ)。
      const seg = SEGMENTS[5];   // 1つのgift演出にgift 3件(連投)
      await openCover({
        "PATCH /api/highlights/7/segments/501/gifts/9501": {
          segment: { ...seg,
                     gifts: [{ ...seg.gifts[0], cut_start: 55.0, cut_end: 58.0, cut_own: true },
                             seg.gifts[1], seg.gifts[2]] },
        },
      }, { playable: true });
      await selectRow("Rose");
      key(",", null, { shiftKey: true });         // 尻 -1.0
      key(",", null, { shiftKey: true });         // 尻 -1.0(合わせて 60.0 → 58.0)
      await settleCut();

      const patch = page.calls.fetches.find((f) => f.method === "PATCH");
      expect(patch.url).toBe("/api/highlights/7/segments/501/gifts/9501");
      const spans = rows("cv-rows")
        .filter((tr) => tr.textContent.includes("Rose"))
        .map((tr) => cellText(tr)[4]);
      expect(spans).toEqual(["0:55.0〜0:58.0"]);
    });

    it("区間はgift演出の外へは出せない(送らずに理由を出す)", async () => {
      // montageなのでgift演出の外は「その少し前」ではなく**まったく無関係な場面**である。
      // Serverも400で断るが、往復を1回省いて理由をその場で読ませる。
      await openCover({}, { playable: true });
      await selectRow("Guardian's Pledge");
      const before = page.calls.fetches.length;
      key("[", null, { shiftKey: true });         // 頭 -1.0(gift演出は 45.0〜54.0)
      await settleCut();
      expect(page.calls.fetches.length).toBe(before);
      expect(doc.body.textContent).toContain("区間は 0:45.0〜0:54.0 の中へ");
      // 表の値も動かさない(送っていないのに表だけ新しいと、直したつもりで進む)。
      expect(cellText(rowOf("Guardian's Pledge"))[4]).toBe("0:45.0〜0:54.0");
    });

    it("[ ] , . キーで区間を刻んで動かし、連打は1回にまとめて送る", async () => {
      // **キーだけで詰め切れることが要件**である。全体の軸では6秒のgift演出が70pxしか無く、
      // 0.25秒が3pxで、dragでは詰め切れなかった。
      //
      // **打鍵ごとには送らない。** 0.25秒ずつ20回叩けば20往復になり、途中の値が全部DBを
      // 通って、結末の名乗りも20枚積み上がる。画面は打った瞬間に動き、送るのは手が
      // 止まってから1回だけである。
      await openCover({
        "PATCH /api/highlights/7/segments/401/gifts/9401": {
          segment: { ...SEGMENTS[4],
                     gifts: [{ ...SEGMENTS[4].gifts[0],
                               cut_start: 45.5, cut_end: 53.0, cut_own: true }] },
        },
      }, { playable: true });
      await selectRow("Guardian's Pledge");
      const before = page.calls.fetches.filter((f) => f.method === "PATCH").length;

      key("]");                                 // 頭 +0.25
      key("]");                                 // 頭 +0.25(合わせて +0.5)
      key(",", null, { shiftKey: true });        // 尻 -1.0
      await page.settle();
      // 打った瞬間に動くのは時間軸の帯だけで、まだ送ってはいない。
      expect(page.calls.fetches.filter((f) => f.method === "PATCH").length).toBe(before);

      await settleCut();
      const sent = page.calls.fetches.filter((f) => f.method === "PATCH");
      // **3打で1回。** 途中の値は1つもDBを通らない。
      expect(sent.length).toBe(before + 1);
      expect(JSON.parse(sent.pop().body)).toEqual({ cut_start: 45.5, cut_end: 53 });
    });

    it("矢印は押した向きへ区間を縮め、Ctrlを添えると同じ向きへ伸ばす", async () => {
      // **どちらの端が動くかを覚えずに詰め切れることが要件**である。[ ] , . は端を名指しで
      // 動かす手だが、4つの綴りと2つの端の対応を頭で引くのは数百件を潰す面では重い。
      // 矢印は「帯が押した向きへ動く」だけで読める —— 素で押せば縮み(←は尻を左へ、
      // →は頭を右へ)、Ctrlを添えると同じ向きへ伸びる(Ctrl+←は頭を左へ、Ctrl+→は尻を右へ)。
      await openCover({
        "PATCH /api/highlights/7/segments/401/gifts/9401": {
          segment: { ...SEGMENTS[4],
                     gifts: [{ ...SEGMENTS[4].gifts[0],
                               cut_start: 45.5, cut_end: 53.5, cut_own: true }] },
        },
      }, { playable: true });
      await selectRow("Guardian's Pledge");   // gift演出は 45.0〜54.0

      key("ArrowRight");                      // 頭 +0.25(縮む)
      key("ArrowRight");
      key("ArrowRight");                      // 45.0 → 45.75
      key("ArrowLeft");                       // 尻 -0.25(縮む)
      key("ArrowLeft");
      key("ArrowLeft");                       // 54.0 → 53.25
      key("ArrowLeft", null, { ctrlKey: true });    // 頭 -0.25(伸びる)45.75 → 45.5
      key("ArrowRight", null, { ctrlKey: true });   // 尻 +0.25(伸びる)53.25 → 53.5
      await page.settle();
      // 連打は1回にまとめて送る([ ] , . と同じ口を通るので、途中の値はDBを通らない)。
      expect(page.calls.fetches.filter((f) => f.method === "PATCH").length).toBe(0);

      await settleCut();
      const sent = page.calls.fetches.filter((f) => f.method === "PATCH");
      expect(sent.length).toBe(1);
      expect(JSON.parse(sent[0].body)).toEqual({ cut_start: 45.5, cut_end: 53.5 });
      expect(cellText(rowOf("Guardian's Pledge"))[4]).toBe("0:45.5〜0:53.5");
    });

    it("Shiftを添えた矢印も刻みが4倍になる", async () => {
      // 刻みの倍率は綴りごとに散らさない。[ ] , . と同じく Shift で 0.25→1.0 秒にする。
      await openCover({
        "PATCH /api/highlights/7/segments/401/gifts/9401": {
          segment: { ...SEGMENTS[4],
                     gifts: [{ ...SEGMENTS[4].gifts[0],
                               cut_start: 46.0, cut_end: 53.0, cut_own: true }] },
        },
      }, { playable: true });
      await selectRow("Guardian's Pledge");
      key("ArrowRight", null, { shiftKey: true });  // 頭 +1.0
      key("ArrowLeft", null, { shiftKey: true });   // 尻 -1.0
      await settleCut();
      expect(cellText(rowOf("Guardian's Pledge"))[4]).toBe("0:46.0〜0:53.0");
    });

    it("端を刻んだら、その端の絵をその場で出す(再生は始めない)", async () => {
      // **数字と帯だけが動いて映像が前のままでは、詰める操作が完結しない。** 0.25秒詰めた
      // 結果が「切れて良い場面か」は端の絵でしか判らないので、頭を動かしたら頭、尻を
      // 動かしたら尻へ飛ぶ。ここから流したい訳ではないので**再生は始めない**。
      await openCover({
        "PATCH /api/highlights/7/segments/401/gifts/9401": {
          segment: { ...SEGMENTS[4],
                     gifts: [{ ...SEGMENTS[4].gifts[0],
                               cut_start: 45.25, cut_end: 53.75, cut_own: true }] },
        },
      }, { playable: true });
      await selectRow("Guardian's Pledge");   // gift演出は 45.0〜54.0
      const video = doc.getElementById("cv-video");
      const plays = page.calls.mediaPlays.length;

      key("ArrowRight");                            // 頭 45.0 → 45.25
      expect(video.currentTime).toBeCloseTo(45.25, 3);
      key("ArrowLeft");                             // 尻 54.0 → 53.75
      expect(video.currentTime).toBeCloseTo(53.75, 3);
      key("ArrowLeft", null, { ctrlKey: true });    // 頭 45.25 → 45.0
      expect(video.currentTime).toBeCloseTo(45.0, 3);
      key("ArrowRight", null, { ctrlKey: true });   // 尻 53.75 → 54.0
      expect(video.currentTime).toBeCloseTo(54.0, 3);
      // 端を名指しで動かす綴りも同じ道を通る(刻む口が1つだからである)。
      key("]");                                     // 頭 45.0 → 45.25
      expect(video.currentTime).toBeCloseTo(45.25, 3);
      key(",");                                     // 尻 54.0 → 53.75
      expect(video.currentTime).toBeCloseTo(53.75, 3);

      // **端を1つ観るための移動である。** ここから流し始めると、詰めるたびに次の場面まで
      // 流れて、今どの端を見ているのかが分からなくなる。
      expect(page.calls.mediaPlays.length).toBe(plays);
      await settleCut();
      expect(cellText(rowOf("Guardian's Pledge"))[4]).toBe("0:45.3〜0:53.8");
    });

    it("絞り込みの群にfocusが在る間、矢印は区間を動かさない", async () => {
      // 絞り込み・並びの群も矢印で段を送る。1打で段と区間の両方が動くと、どちらが
      // 動いたのかが読めないまま、見ていない行の区間が黙って0.25秒ずれる。
      await openCover({}, { playable: true });
      await selectRow("Guardian's Pledge");
      const item = doc.getElementById("cv-filter").querySelector('[data-value="all"]');
      key("ArrowRight", item);
      await settleCut();
      expect(page.calls.fetches.filter((f) => f.method === "PATCH").length).toBe(0);
      // 群の側は動いている(打鍵を捨てたのではなく、群のものにしただけである)。
      expect(doc.getElementById("cv-filter").value).toBe("unchecked");
    });

    it("溜めた刻みは、次の行へ送る前に捨てずに保存する", async () => {
      // 詰めた直後に↑↓で送ると、送る前の値が消えて「直したのに残っていない」という
      // 壊れ方をする。
      await openCover({
        "PATCH /api/highlights/7/segments/401/gifts/9401": {
          segment: { ...SEGMENTS[4],
                     gifts: [{ ...SEGMENTS[4].gifts[0],
                               cut_start: 45.25, cut_end: 54.0, cut_own: true }] },
        },
      }, { playable: true });
      await selectRow("Guardian's Pledge");
      key("]");
      await page.settle();
      key("ArrowDown");                          // 送る前に次の行へ
      await page.settle();
      const sent = page.calls.fetches.filter((f) => f.method === "PATCH");
      expect(sent.length).toBe(1);
      expect(JSON.parse(sent[0].body)).toEqual({ cut_start: 45.25, cut_end: 54 });
    });

    it("Zで直前の区間の変更を1手だけ戻せる(連打1回ぶんをまとめて戻す)", async () => {
      // Serverには機械が出した窓へ戻る道が無い(端を動かした時点で上書きされる)ので、
      // 取り消しは画面が持つしかない。控えは**連打の1手目でだけ**採る —— 1打ごとに
      // 上書きすると、Zが0.25秒ぶんしか戻らず、連打の前へは二度と戻れない。
      await openCover({
        "PATCH /api/highlights/7/segments/401/gifts/9401": {
          segment: { ...SEGMENTS[4],
                     gifts: [{ ...SEGMENTS[4].gifts[0],
                               cut_start: 45.75, cut_end: 54.0, cut_own: true }] },
        },
      }, { playable: true });
      await selectRow("Guardian's Pledge");
      key("]");
      key("]");
      key("]");
      await page.settle();
      key("z");
      await page.settle();
      const sent = page.calls.fetches.filter((f) => f.method === "PATCH");
      // 溜めていた刻みは**送らずに捨てる**(戻す操作なので、送ってから戻すのは往復の無駄)。
      expect(sent.length).toBe(1);
      // 戻す先は**触る前の状態**。触る前はgift演出の窓のままだったので、区間そのものを捨てる。
      expect(JSON.parse(sent[0].body)).toEqual({ cut_clear: true });
    });

    it("相席の行はそれと判る", async () => {
      // 区間はgiftごとなので、詰めても相手は動かない。
      await openCover({}, { playable: true });
      expect(cellText(rowOf("Lion"))[7]).toContain("相席");
      // 連投(同じ人が3件)は相席ではない。**人数であって件数ではない。**
      expect(cellText(rowOf("Rose"))[7]).not.toContain("相席");
    });

    it("相席のgift演出でも、片方の区間を詰めて相手は動かない", async () => {
      // **これが今回の作りが解いた事故そのものである。** gift演出の窓を「その行の区間」と
      // していた頃は、視聴者Aの行で詰めた6秒が視聴者Eのfileでも同じ長さで切られていた。
      const seg = SEGMENTS[6];
      await openCover({
        "PATCH /api/highlights/7/segments/701/gifts/9701": {
          segment: { ...seg,
                     gifts: [{ ...seg.gifts[0], cut_start: 64.0, cut_end: 67.0,
                               cut_own: true },
                             seg.gifts[1]] },
        },
      }, { playable: true });
      await selectRow("Lion");
      key(",", null, { shiftKey: true });         // 尻 -1.0(70.0 → 69.0)
      await settleCut();

      expect(cellText(rowOf("Lion"))[4]).toBe("1:04.0〜1:07.0");
      expect(cellText(rowOf("Heart Me"))[4]).toBe("1:04.0〜1:10.0");
    });

    // 戻す道は**Zキー1つだけ**である。以前は「自動の範囲に戻す」と「区間を元に戻す」の
    // 2つのbuttonが並んでいて、どちらが何を戻すのかが読めなかった(利用者の指摘)。片方に
    // 畳んだ後も「切り出す範囲」の枠にbuttonとして残っていたが、枠ごと外した(同上) ――
    // 自動の範囲から初めて動かした直後にZを押せば、自動の範囲そのものへ戻る。

    // ===== 既定の窓の頭は「映像が切り替わり終わる秒」 =====
    // gift演出の境目は**音**で決まっている。TikTokのmontageは音を一瞬で切り替えながら映像には
    // 切り替わりの演出を掛けるので(実測29箇所で映像は中央値0.60秒あと、手前に出た境目は
    // 0件)、境目をそのまま頭にすると**全部の切り出しの頭に前のgiftの場面が残る**。
    // 数字だけを出すと「なぜgift演出の頭とずれているのか」が読めないので、出所を名乗らせる。

    // 映像の頭を持つgift演出1つ。Serverは触っていないgiftの窓もここから作って返す。
    const measured = {
      ...SEGMENTS[4], video_start: 45.83, video_probed: true,
      gifts: [{ ...SEGMENTS[4].gifts[0], cut_start: 45.83, cut_end: 54.0,
                cut_own: false }],
    };
    const withSegment = (seg) => ({
      [`GET /api/highlights/7`]: {
        highlight: HIGHLIGHTS[0],
        segments: [...SEGMENTS.slice(0, 4), seg, ...SEGMENTS.slice(5)],
      },
    });
    // 表の「区間」の列は俯瞰(coverage)の当たりから描く。gift演出の側だけを差し替えても
    // 表は動かないので、名乗りを確かめる test では当たりの側も揃える。
    const withHit = (over) => ({
      [`GET ${URL_COVER}`]: {
        ...COVERAGE,
        items: COVERAGE.items.map((g) => (g.gift_name !== "Guardian's Pledge" ? g : {
          ...g, hits: (g.hits || []).map((h) => ({ ...h, ...over })),
        })),
      },
    });

    it("自動の範囲の開始が映像の頭になり、どこから来たかを名乗る", async () => {
      await openCover({ ...withSegment(measured),
                        ...withHit({ video_start: 45.83, video_probed: true,
                                     cut_start: 45.83 }) }, { playable: true });
      await selectRow("Guardian's Pledge");
      // 頭は音の境目(45.0)ではなく映像の頭。**尻は動かさない** —— gift演出の終わりは次の音の
      // 境目、つまりこの場面の最後の綺麗なframeである。
      expect(cellText(rowOf("Guardian's Pledge"))[4]).toBe("0:45.8〜0:54.0");
      // まだ触っていない行なので、この行だけの区間の印は付かない。**説明の文言は
      // 出さない**(利用者の指定) —— 映像が切り替わり終わる秒は時間軸の点線が出す。
      const span = rowOf("Guardian's Pledge").cells[4].querySelector("span");
      expect(span.classList.contains("st-cut-own")).toBe(false);
      // 数字は欄ではなく**送られる値**でも確かめる ―― 「切り出す範囲」の欄を外した今、
      // 自動の範囲がどこから始まっているかは、1刻み動かした結果にしか出ない。
      key("]");
      await settleCut();
      const patch = page.calls.fetches.filter((f) => f.method === "PATCH").pop();
      expect(JSON.parse(patch.body)).toEqual({ cut_start: 46.08, cut_end: 54 });
    });

    it("切り替わりが決まらないgift演出は、gift演出の境目をそのまま名乗る", async () => {
      // 測っていないのか、測って決まらなかったのかは**言い分けない**。どちらも答えは
      // 「gift演出の境目」で、人が次に打つ手も同じである(利用者の指摘で文言を畳んだ)。
      await openCover({}, { playable: true });
      await selectRow("Guardian's Pledge");
      expect(cellText(rowOf("Guardian's Pledge"))[4]).toBe("0:45.0〜0:54.0");

      await page.close();
      await openCover(withSegment({ ...SEGMENTS[4], video_probed: true }),
                      { playable: true });
      await selectRow("Guardian's Pledge");
      expect(cellText(rowOf("Guardian's Pledge"))[4]).toBe("0:45.0〜0:54.0");
    });

    it("人が詰めた区間は、映像の頭に上書きされない", async () => {
      await openCover({
        ...withSegment({
          ...measured,
          gifts: [{ ...measured.gifts[0], cut_start: 47.0, cut_end: 52.0,
                    cut_own: true }],
        }),
        ...withHit({ video_start: 45.83, video_probed: true,
                     cut_start: 47.0, cut_end: 52.0, cut_own: true }),
      }, { playable: true });
      await selectRow("Guardian's Pledge");
      expect(cellText(rowOf("Guardian's Pledge"))[4]).toBe("0:47.0〜0:52.0");
      // この行だけの区間であることは印(class)で名乗る。文言では言わない。
      expect(rowOf("Guardian's Pledge").cells[4].querySelector("span")
        .classList.contains("st-cut-own")).toBe(true);
      // 触った値がそのまま起点になる(映像の頭 45.83 には戻らない)。
      key("]");
      await settleCut();
      const patch = page.calls.fetches.filter((f) => f.method === "PATCH").pop();
      expect(JSON.parse(patch.body)).toEqual({ cut_start: 47.25, cut_end: 52 });
    });

    it("戻した後は自動の範囲に戻り、続けてZを押しても戻す先は無い", async () => {
      // 戻せる1手は**この面で触った直前の1つだけ**である。戻した後もう1回押せる状態が
      // 残っていると、押した人は「まだ戻せる」と読んで無関係な行を戻すことになる。
      await openCover(withSegment(measured), { playable: true });
      await selectRow("Guardian's Pledge");
      key("]", null);
      await settleCut();
      key("z");
      await settleCut();
      // 戻す先は**触る前の状態** ―― 触る前は自動の範囲のままだったので、この行だけの
      // 区間そのものを捨てる(自動の範囲へ戻る)。
      const patch = page.calls.fetches.filter((f) => f.method === "PATCH").pop();
      expect(JSON.parse(patch.body)).toEqual({ cut_clear: true });
      key("z");
      await page.settle();
      expect(doc.body.textContent).toContain("戻せる区間の変更がありません");
    });
  });

  // ===== 倍速再生 =====
  // 検証tabと出力tabは同じ1つの設定を使い、次に開いた時も同じ速さで始まる。
  describe("倍速再生", () => {
    // segbarのuser操作。摘みを動かすのは中の range で、change は群のrootまで上がる。
    const slide = (id, index) => {
      const range = doc.getElementById(id).querySelector("input[type=range]");
      range.value = String(index);
      range.dispatchEvent(new win.Event("input", { bubbles: true }));
    };
    // data-stops の並び。1x は3、2x は6。
    const AT_2X = 6;

    it("検証で選んだ速さが、出力の摘みと両方のplayerに入る", async () => {
      await openCover({}, { playable: true });
      slide("cv-rate", AT_2X);
      expect(doc.getElementById("cv-rate").value).toBe("2");
      expect(doc.getElementById("ex-rate").value).toBe("2");
      expect(doc.getElementById("cv-video").playbackRate).toBe(2);
      expect(doc.getElementById("ex-video").playbackRate).toBe(2);
      // srcを差し替えるたびに1xへ戻らないよう、読み込み時に当たる方へも入れる。
      expect(doc.getElementById("cv-video").defaultPlaybackRate).toBe(2);
    });

    it("出力で選んでも同じ設定になる(tabごとに選び直させない)", async () => {
      await openCover({}, { playable: true });
      slide("ex-rate", AT_2X);
      expect(doc.getElementById("cv-rate").value).toBe("2");
      expect(doc.getElementById("cv-video").playbackRate).toBe(2);
    });

    it("選んだ速さは次に開いた時も効いている", async () => {
      page = loadPage({
        page: "story",
        routes: routes(),
        before: (win_) => win_.localStorage.setItem("tictok.story.play-rate", "1.5"),
      });
      win = page.win;
      doc = page.document;
      await page.settle();
      expect(doc.getElementById("cv-rate").value).toBe("1.5");
      expect(doc.getElementById("ex-rate").value).toBe("1.5");
      expect(doc.getElementById("cv-video").playbackRate).toBe(1.5);
    });
  });

  describe("Serverの既定値の名乗り", () => {
    it("defaultsは照合側と出力側に分かれて返る(平らなdictとして読まない)", async () => {
      // **これが実際のbugだった。** 平らなdictとして読んでいたためどの欄も既定値を引けず、
      // 「Server既定」の文字が欄の幅で切れて「Serv」とだけ出ていた —— 設定が壊れている
      // ように見えていたのはこれで、値そのものはServer側で正しく効いていた。
      await open();
      const ph = (id) => doc.getElementById(id).placeholder;
      // 照合側(探す範囲)。**単位の絵文字は欄の中に入れない**(利用者の指摘) —— placeholderは
      // 欄の中に薄字で出るので、初期表示では「入力欄に絵文字が入っている」ようにしか
      // 見えなかった。単位は欄の左のlabelが名乗っている。
      expect(ph("opt-min-diamonds")).toBe("98");
      expect(ph("opt-window")).toBe("5");
      // **遡る日数だけは既定が1つに決まらない。** 狭い窓で1本も当たらなければ広げて
      // もう一度走るので、単数の数字を出すと「その窓しか見ない」と読めてしまう。
      expect(ph("opt-days")).toBe("14→30日");
      // 薄字が唯一の名乗りで、tooltipへ同じことを書き足さない(利用者の指定)。
      expect(doc.getElementById("opt-days").title).toBe("");
      // 出力側(出来上がりの中身)。**同じ min_diamonds でも別の数字である。**
      expect(ph("ex-min")).toBe("1,000");
      expect(ph("ex-pad-lead")).toBe("0.3");
      // 検証の面の下限は照合側と同じ出所がServerで効く。
      expect(ph("cv-min")).toBe("98");
      // 候補の範囲も「既定」だけでは何が効くのか読めない。
      expect(doc.getElementById("opt-scope").querySelector('[data-value=""]').textContent)
        .toBe("既定（gift地点）");
      // 実際に効く値の名乗りは薄字1箇所だけ。tooltipで言い直さない。
      expect(doc.getElementById("ex-min").title).toBe("");
    });

    it("Serverが名乗らない既定は数字を作らず短い語で済ませる", async () => {
      // 欄は数値のために狭い。長い文字列をplaceholderへ入れても幅で切れて意味の無い
      // gift演出が出るだけで、**画面が数字を作れば設定を変えてもそこだけ古い値を名乗る。**
      await open({ [`GET ${URL_LIST}`]: { items: HIGHLIGHTS } });
      expect(doc.getElementById("opt-min-diamonds").placeholder).toBe("既定");
      expect(doc.getElementById("ex-min").placeholder).toBe("既定");
      expect(doc.getElementById("cv-min").placeholder).toBe("既定");
      expect(doc.getElementById("opt-scope").querySelector('[data-value=""]').textContent)
        .toBe("既定");
    });
  });

  describe("書き出しの前に判ること", () => {
    const PLAN = {
      week_label: "8/29 〜 9/5",
      counts: { total: 3, selected: 3 },
      files: [{
        nickname: "視聴者A🐢💤", user_unique_id: "viewer_a", identity_key: "k1", rank: 1,
        position: 1, coin: 13543, diamonds: 10999, seconds: 18.0,
        filename: EXPORT_FILE,
        count: 2,
        items: [
          { start: 12.0, end: 21.0, highlight_id: 7, at: 14.5,
            segment_id: 101, gift_name: "Goal Highlight", gift_id: 5655, diamonds: 6000,
            user_nickname: "視聴者A🐢💤", identity_key: "k1",
            confidence: "high", approved: true,
            frame_url: "/api/highlights/7/frame?at=14.500", frame_clamped: false,
            recording_frame_url: "/api/highlights/7/segments/101/frame?at=14.500" },
          // **これが事故そのもの。** 視聴者Aのfileに、よいが投げたgiftが入っている。
          { start: 45.0, end: 54.0, highlight_id: 7, at: 47.2,
            segment_id: 401, gift_name: "Guardian's Pledge", gift_id: 1, diamonds: 4999,
            user_nickname: "視聴者C🐢💤 ｻｲｺｳｯ!", identity_key: "k5",
            confidence: "low", approved: false,
            frame_url: "/api/highlights/7/frame?at=47.200", frame_clamped: false,
            recording_frame_url: "/api/highlights/7/segments/401/frame?at=47.200" },
        ],
        // **実際に切る窓。** ``items``(gift 1件ずつの記録)とは1対1にならない ―― 連投は
        // 記録6件・窓1つになる。通し再生と章の帯はこちらを読む。
        cuts: [
          { start: 12.0, end: 21.0, seconds: 9.0, highlight_id: 7, diamonds: 6000,
            segment_ids: [101], gift_event_ids: [900],
            gifts: [{ gift_event_id: 900, gift_name: "Goal Highlight", diamonds: 6000,
                      user_nickname: "視聴者A🐢💤" }] },
          { start: 45.0, end: 54.0, seconds: 9.0, highlight_id: 7, diamonds: 4999,
            segment_ids: [401], gift_event_ids: [904],
            gifts: [{ gift_event_id: 904, gift_name: "Guardian's Pledge",
                      diamonds: 4999, user_nickname: "視聴者C🐢💤 ｻｲｺｳｯ!" }] },
        ],
      }],
      skipped: [],
    };

    async function plan(over = {}, opts = {}) {
      await open({ "POST /api/highlights/export/plan": PLAN, ...over }, opts);
      // **開けば素材(=その週の当たり)が決まり、下見も自動で引かれる。**
      doc.getElementById("tab-export").click();
      await page.settle();
    }

    it("場面の絵は出さない(行が高くなるぶん、一度に読める件数が減る)", async () => {
      // **絵は外した。** 別人のgiftが混ざっていないかは gifter の列で読み、実際に何が
      // 映っているかは行の▶(素材から1件だけ再生)で確かめる —— 絵1枚より動く物が強い。
      await plan();
      expect(doc.querySelectorAll("#ex-rows .st-frame").length).toBe(0);
      // 残ってよい絵はgiftのiconとgifterのavatarだけで、**動画の場面は1枚も無い**。
      expect(Array.from(doc.querySelectorAll("#ex-rows img"))
        .filter((img) => String(img.getAttribute("src") || "").includes("/frame")))
        .toEqual([]);
      rows("ex-rows")[0].querySelector(".st-caret").click();
      expect(doc.querySelectorAll("#ex-rows .st-subitem .st-frame").length).toBe(0);
    });

    it("束を開くと1件ずつの行と、言い切れていない印が出る", async () => {
      // 「未確認」の印は出さない ―― 確認済を付ける口を画面から外したので、全ての行に
      // 付く帯になり、その行だけの事情がその中に埋もれる(利用者の指定)。
      await plan();
      rows("ex-rows")[0].querySelector(".st-caret").click();
      const items = Array.from(doc.querySelectorAll("#ex-rows .st-subitem"));
      expect(items.length).toBe(2);
      expect(items[1].classList.contains("st-risk")).toBe(true);
      expect(items[1].querySelector(".st-sub-mark").textContent).toContain("要確認");
      expect(items[1].querySelector(".st-sub-mark").textContent).not.toContain("未確認");
      expect(items[0].classList.contains("st-risk")).toBe(false);
    });

    it("1本に載らなかったgiftを、理由つきで束の中へ並べる", async () => {
      // **無い物こそ読みどころである。** 照合結果だけを並べると、TikTokが選ばなかった
      // giftも人が外したgiftも「画面に無い」で一括りになり、何が足りないのか判らない。
      const withMissing = {
        ...PLAN,
        files: [{
          ...PLAN.files[0],
          missing_count: 2, missing_diamonds: 1298,
          missing: [
            { gift_event_id: 911, label: "08/30 21:04", gift_name: "Fireworks",
              diamonds: 1088, gift_count: 1, unit_diamonds: 1088,
              user_nickname: "視聴者A🐢💤", identity_key: "k1",
              highlight_ids: [], reason: "どのハイライトにも出ていません" },
            { gift_event_id: 912, label: "08/31 22:10", gift_name: "Hearts",
              diamonds: 210, gift_count: 1, unit_diamonds: 210,
              user_nickname: "視聴者A🐢💤", identity_key: "k1",
              highlight_ids: [9], reason: "別のハイライトに在りますが、素材に選んでいません" },
          ],
        }],
      };
      await plan({ "POST /api/highlights/export/plan": withMissing });
      // 束を開く前に、件数の列で「落ちている物がある」と判る。
      expect(rows("ex-rows")[0].querySelector(".st-miss-n").textContent).toContain("2");
      rows("ex-rows")[0].querySelector(".st-caret").click();
      const missing = Array.from(doc.querySelectorAll("#ex-rows .st-missitem"));
      expect(missing.length).toBe(2);
      // 理由はServerの文言そのまま。画面で言い換えると説明が2箇所に増える。
      expect(missing[0].textContent).toContain("どのハイライトにも出ていません");
      expect(missing[1].textContent).toContain("素材に選んでいません");
      // **出力の行とは見分けが付く**(出力の中身ではないため)。
      expect(missing[0].classList.contains("st-subitem")).toBe(true);
      expect(doc.querySelector("#ex-rows .st-misshead").textContent).toContain("未収録 2");
    });

    it("まとめ投げは単価×個数を添える(合計だけでは演出の有無が読めない)", async () => {
      const combo = {
        ...PLAN,
        files: [{
          ...PLAN.files[0],
          items: [{ ...PLAN.files[0].items[0], diamonds: 1990, gift_count: 10,
                    unit_diamonds: 199 }],
        }],
      };
      await plan({ "POST /api/highlights/export/plan": combo });
      rows("ex-rows")[0].querySelector(".st-caret").click();
      const coin = doc.querySelector("#ex-rows .st-subitem .st-sub-d");
      expect(coin.textContent).toContain("🪙1,990");
      expect(coin.querySelector(".st-sub-each").textContent).toBe("199×10");
    });

    it("ハイライトに1件も出ていない対象gifterを出す(黙って消さない)", async () => {
      // 週合計が下限を越えているのに1本も出来ない人は、以前どこにも現れなかった。
      const uncovered = {
        ...PLAN,
        uncovered: [{
          identity_key: "k9", nickname: "視聴者G", coin: 4200,
          missing_count: 1, missing_diamonds: 1088,
          missing: [{ gift_event_id: 950, label: "08/30 20:00", gift_name: "Fireworks",
                      diamonds: 1088, reason: "どのハイライトにも出ていません" }],
        }],
      };
      await plan({ "POST /api/highlights/export/plan": uncovered });
      // **表の外に説明の段は作らない**(利用者の指定)。gifterの表の行として並べ、
      // fileにならないことは行の警告色と gifter の脇の印で名乗る。
      expect(doc.getElementById("ex-skipped")).toBeNull();
      const row = rows("ex-rows").find((tr) => tr.classList.contains("st-nofile"));
      expect(row).toBeTruthy();
      expect(row.textContent).toContain("視聴者G");
      expect(row.querySelector(".st-nofile-tag").textContent).toContain("fileにならない");
      const cells = cellText(row);
      expect(cells[0]).toBe("—");
      // 1本にも入らないので「0」、その脇に何件が行き場を失ったかを添える。
      expect(cells[2]).toContain("0");
      expect(cells[2]).toContain("未収録1");
      expect(cells[3]).toBe("4,200");
      expect(cells[4]).toBe("—");
      // 理由はtooltipが持つ。行の中で文章にはしない。
      expect(row.title).toContain("どこにも出ていません");
    });

    it("束の持ち主と違うgifterのgift演出を、束を開いた行で名乗る", async () => {
      // **これが今回の事故そのもの。** 以前は「同じ人のgift演出が並ぶ」前提でgifterを省いて
      // いたため、別人のgiftが混ざっても行からは読めなかった。
      await plan();
      rows("ex-rows")[0].querySelector(".st-caret").click();
      const items = Array.from(doc.querySelectorAll("#ex-rows .st-subitem"));
      expect(items[0].classList.contains("st-foreign")).toBe(false);
      expect(items[1].classList.contains("st-foreign")).toBe(true);
      // 名前そのものが行に出る(絵と併せて二重に気付ける)。
      expect(items[1].querySelector(".st-sub-who").textContent).toContain("視聴者C");
      // 混ざっていることは色で名乗る(文章では言い直さない)。
      expect(items[1].querySelector(".st-sub-who").classList.contains("st-risk-text"))
        .toBe(true);
      // **持ち主と同じ人の行には名前を出さない**(利用者の指摘)。束の見出しに出ている
      // 名前が中の行にも何十回と並ぶだけで、行の幅を食って読みにくくなっていた ――
      // 名前が出ている行が1行だけになることで、混ざった別人はかえって目に立つ。
      expect(items[0].querySelector(".st-sub-who")).toBeNull();
    });

    it("束ねたサブアカウントのgiftは別人として名乗らない", async () => {
      // 配信者画面で束ねた相手(user_merges)は同じ人である。アカウント(identity_key)で
      // 比べていた頃は、束ねた人が自分のサブアカウントで投げたgiftのたびに
      // 「別人が混ざっている」と名乗られていた。比べるのはServerが畳んだ person_key。
      const merged = {
        ...PLAN,
        files: [{
          ...PLAN.files[0],
          accounts: 2,
          items: [
            { ...PLAN.files[0].items[0], person_key: "k1" },
            // 主とは別のアカウントで投げたgift。畳み先は同じ人である。
            { ...PLAN.files[0].items[1], identity_key: "k2", person_key: "k1",
              user_nickname: "視聴者Aのサブ" },
          ],
        }],
      };
      await plan({ "POST /api/highlights/export/plan": merged });
      rows("ex-rows")[0].querySelector(".st-caret").click();
      const items = Array.from(doc.querySelectorAll("#ex-rows .st-subitem"));
      expect(items[1].classList.contains("st-foreign")).toBe(false);
      // 同じ人なので名前も出さない(束の見出しと同じ名前を並べない)。
      expect(items[1].querySelector(".st-sub-who")).toBeNull();
      // 何アカウントぶんの1本なのかは、束の見出しの脇で名乗る。
      expect(rows("ex-rows")[0].querySelector(".st-merged").textContent)
        .toContain("統合 2");
    });

    it("gift件数はServerが数えた値を出す(items.lengthで代用しない)", async () => {
      // 連投は畳まずに全件並べるが、出力側は同じgifterの重なる窓を1つへ畳むので、
      // 件数と尺は比例しない。数え方を画面が持つと予告と成果物が食い違う。
      await plan();
      expect(Array.from(rows("ex-rows")[0].cells).map((c) => c.textContent.trim()))
        .toContain("2");
      const bare = { ...PLAN, files: [{ ...PLAN.files[0], count: undefined }] };
      await page.close();
      await plan({ "POST /api/highlights/export/plan": bare });
      // 名乗られなければ数を作らない。
      expect(Array.from(rows("ex-rows")[0].cells)[2].textContent.trim()).toBe("—");
    });

    it("file名のlabelは送らない(Serverが422で弾く)", async () => {
      await plan({ "POST /api/highlights/export": { job_id: 1 } });
      const body = JSON.parse(
        page.calls.fetches.find((f) => f.url === "/api/highlights/export/plan").body);
      expect(body).not.toHaveProperty("name");
      expect(body).not.toHaveProperty("group_by_gifter");
    });

    // **表の上に常設の警告boxは置かない。** そこで読んでも打つ手は変わらず(外すのは
    // 検証tabのNG)、表と操作の間に挟まった読み飛ばされる帯になっていた(利用者の指定)。
    // 名乗りは下の「押した後の確認」だけが持つ ―― 進む/やめるを選べる場所である。
    it("表の上に常設の警告boxを置かない", async () => {
      await plan();
      expect(doc.querySelector(".st-warnbox")).toBeNull();
      expect(doc.getElementById("view-export").textContent)
        .not.toContain("書き出す前に確かめてください");
    });

    it("押した後も確認を挟む(押させないのではなく、押す前に判る)", async () => {
      await plan({ "POST /api/highlights/export": { job_id: 1 } });
      doc.getElementById("ex-run").click();
      await page.settle();
      const modal = doc.querySelector(".confirm-modal");
      expect(modal).toBeTruthy();
      expect(modal.textContent).toContain("要確認 1件");
      // 取り消したら投げない。
      modal.querySelector(".btn:not(.btn-danger)").click();
      await page.settle();
      expect(page.calls.fetches.some((f) => f.url === "/api/highlights/export")).toBe(false);
    });

    it("確からしさの高い束では余計な確認を出さない", async () => {
      const clean = {
        ...PLAN,
        files: [{
          ...PLAN.files[0],
          items: PLAN.files[0].items.map((i) => ({ ...i, approved: true, confidence: "high" })),
        }],
      };
      await plan({ "POST /api/highlights/export/plan": clean,
                   "POST /api/highlights/export": { job_id: 1 } });
      doc.getElementById("ex-run").click();
      await page.settle();
      expect(doc.querySelector(".confirm-modal")).toBeNull();
      expect(page.calls.fetches.some((f) => f.url === "/api/highlights/export")).toBe(true);
    });

    it("Serverが確からしさを名乗らないなら、判断できないことを名乗る", async () => {
      const bare = {
        ...PLAN,
        files: [{
          ...PLAN.files[0],
          items: PLAN.files[0].items.map(({ confidence, ...rest }) => rest),
        }],
      };
      await plan({ "POST /api/highlights/export/plan": bare });
      // 印が無いことを0件として描かない —— 確かめていないgift演出が、確かめた物と同じ
      // 見え方になる。名乗る場所は書き出しを押した後の確認である。
      doc.getElementById("ex-run").click();
      await page.settle();
      const modal = doc.querySelector(".confirm-modal");
      expect(modal).toBeTruthy();
      expect(modal.textContent).toContain("確からしさ 不明");
    });

    // 書き出した後に中身を確かめる手段が無かったので、別人のgiftが混ざったfileは
    // 配ってから気付くしかなかった。**成果物を同じ面で観られること**が要件である。
    it("置き場の書き出し済みfileが棚に並び、clickで右のplayerに載る", async () => {
      await open({}, { playable: true });
      doc.getElementById("tab-export").click();
      await page.settle();
      const files = Array.from(doc.querySelectorAll("#ex-files .st-filepick"));
      expect(files.length).toBe(EXPORTS.items.length);
      expect(files[0].textContent).toContain("視聴者A🐢💤");
      expect(doc.getElementById("ex-files-note").textContent).toBe("2");
      // 検証用の書き出し(DBの実照合と突き合わせていない物)は印で名乗る。
      expect(files[1].classList.contains("st-risk")).toBe(true);
      expect(files[1].title).toContain("⚠ 未検証");

      files[0].click();
      await page.settle();
      const video = doc.getElementById("ex-video");
      expect(video.getAttribute("src")).toBe(EXPORTS.items[0].url);
      // 動画の上に名乗りの段は置かない(利用者の指定)。観ている1本は表の行の印で読む。
      expect(doc.getElementById("ex-play-head")).toBeNull();
    });

    it("引けなかった書き出し済みfileを0件として描かない", async () => {
      // 置き場に在るのに引けないのと、まだ書き出していないのは別の話である。
      await open({
        [`GET ${URL_EXPORTS}`]: () =>
          new win.Response(JSON.stringify({ detail: "落ちました" }), { status: 500 }),
      });
      doc.getElementById("tab-export").click();
      await page.settle();
      const empty = doc.getElementById("ex-files-empty");
      expect(empty.classList.contains("list-failed")).toBe(true);
      expect(doc.querySelectorAll("#ex-files .st-filepick").length).toBe(0);
    });

    it("束を開いたgift演出の ▶ は、素材のハイライトのその区間を観せる", async () => {
      // 絵は1 frameでしかなく、演出が本当に映っているかは動いている物を観ないと判らない。
      // **書き出す前に実物で確かめられる唯一の場所**である。
      await plan({}, { playable: true });
      rows("ex-rows")[0].querySelector(".st-caret").click();
      const items = Array.from(doc.querySelectorAll("#ex-rows .st-subitem"));
      items[1].querySelector(".st-playbtn").click();
      await page.settle();
      const video = doc.getElementById("ex-video");
      // 素材の再生URLはServerが名乗った物(台帳のurl)だけを使う。
      expect(video.getAttribute("src")).toBe(MEDIA_7);
      // 読み込みが終わってから頭出しする(jsdomは自分ではmetadataを出さない)。
      video.dispatchEvent(new win.Event("loadedmetadata"));
      expect(video.currentTime).toBeCloseTo(45.0, 3);
      // 観ている束は表の行の印で読む(動画の上には何も置かない)。
      expect(rows("ex-rows")[0].classList.contains("st-current")).toBe(true);
    });

    it("素材の再生URLが無ければ ▶ を押せなくする", async () => {
      // pathから組み立てると、置き場の決まりが変わった瞬間に実在しないURLを黙って指す。
      // 押せないことはbuttonそのものが名乗る(理由の文言は置かない)。
      await plan({ [`GET ${URL_LIST}`]: {
        items: [{ ...HIGHLIGHTS[0], url: undefined }], defaults: DEFAULTS } });
      rows("ex-rows")[0].querySelector(".st-caret").click();
      const play = doc.querySelector("#ex-rows .st-subitem .st-playbtn");
      expect(play.disabled).toBe(true);
      expect(play.title).toBe("");
    });

    it("書き出し済みの束は下見の行からも観られる", async () => {
      // 置き場に同じfile名が在る束にだけ ▶ が付く(まだ書き出していない束は押せない)。
      await plan({}, { playable: true });
      const play = rows("ex-rows")[0].querySelector(".st-playbtn");
      expect(play.disabled).toBe(false);
      play.click();
      await page.settle();
      expect(doc.getElementById("ex-video").getAttribute("src"))
        .toBe(EXPORTS.items[0].url);
    });

    it("出力の行をclickすると再生し、その人のgift演出も開く", async () => {
      // 観ている1本の中身を確かめるのがこの面の用なので、選んだ行の内訳は開いた状態で
      // 待っている。閉じるのはcaret(押しただけでは再生は動かない)。
      await plan({}, { playable: true });
      const row = rows("ex-rows")[0];
      row.click();
      await page.settle();
      expect(doc.getElementById("ex-video").getAttribute("src"))
        .toBe(EXPORTS.items[0].url);
      expect(row.nextElementSibling.classList.contains("hidden")).toBe(false);
      expect(row.querySelector(".st-caret").getAttribute("aria-expanded")).toBe("true");
      row.querySelector(".st-caret").click();
      expect(row.nextElementSibling.classList.contains("hidden")).toBe(true);
      // caretを押しただけで再生が始まったり、載っているfileが差し替わったりしない。
      expect(doc.getElementById("ex-video").getAttribute("src"))
        .toBe(EXPORTS.items[0].url);
    });

    it("開いてある行を選び直しても畳まない", async () => {
      // 選択のたびに開閉を切り替えると、caretで開けた物が選び直しで閉じる。
      await plan({}, { playable: true });
      const row = rows("ex-rows")[0];
      row.querySelector(".st-caret").click();
      expect(row.nextElementSibling.classList.contains("hidden")).toBe(false);
      row.click();
      await page.settle();
      expect(row.nextElementSibling.classList.contains("hidden")).toBe(false);
    });

    it("まだ書き出していない行のclickは、繋ぐ順の下見になる", async () => {
      // 押して何も起きないと、押した人はbuttonが無いのか壊れているのかを判じられない。
      // 置き場に同じfile名が無い束(=まだ書き出していない)で確かめる。
      await plan({ [`GET ${URL_EXPORTS}`]: { ...EXPORTS, exists: false, items: [] } },
                 { playable: true });
      rows("ex-rows")[0].click();
      await page.settle();
      const video = doc.getElementById("ex-video");
      expect(video.getAttribute("src")).toBe(MEDIA_7);
      // 観ているのがどの束かは表の行の印で読む(動画の上には何も置かない)。
      expect(rows("ex-rows")[0].classList.contains("st-current")).toBe(true);
    });

    it("gift演出の行はclickでその1件を観せる(▶を狙わせない)", async () => {
      await plan({}, { playable: true });
      rows("ex-rows")[0].querySelector(".st-caret").click();
      const items = Array.from(doc.querySelectorAll("#ex-rows .st-subitem"));
      items[1].click();
      await page.settle();
      const video = doc.getElementById("ex-video");
      expect(video.getAttribute("src")).toBe(MEDIA_7);
      video.dispatchEvent(new win.Event("loadedmetadata"));
      expect(video.currentTime).toBeCloseTo(45.0, 3);
    });

    it("前の1件の見張りは、次の1件を押した時点で外れる", async () => {
      // 見張りは自分の終端まで来て初めて自分を外す。終わる前に別の1件へ移ると古い終端の
      // 見張りが残り、**次の1件が押した瞬間に止まる**(前の窓の終端を既に過ぎているため)。
      await plan({}, { playable: true });
      rows("ex-rows")[0].querySelector(".st-caret").click();
      const items = Array.from(doc.querySelectorAll("#ex-rows .st-subitem"));
      const video = doc.getElementById("ex-video");
      items[0].click();                       // 12.0〜21.0
      await page.settle();
      video.dispatchEvent(new win.Event("loadedmetadata"));
      expect(video.currentTime).toBeCloseTo(12.0, 3);
      items[1].click();                       // 45.0〜54.0(前の終端21.0は過ぎている)
      await page.settle();
      expect(video.currentTime).toBeCloseTo(45.0, 3);
      let paused = false;
      video.pause = () => { paused = true; };
      video.dispatchEvent(new win.Event("timeupdate"));
      expect(paused).toBe(false);
    });
  });

  // ===== 出来上がりを通しで観る =====
  // **1本のmp4は3〜8個の窓を繋いだ物である。** 繋ぎ目はmp4の中に印が無く、素材が複数の
  // ハイライトへ跨ることもある。ここまで画面に在ったのは「書き出し済みを頭から流す」と
  // 「下見の1件だけを流す」の2つで、**これから作る1本を順番どおり確かめる道が無かった**。
  describe("出来上がりを通しで観る", () => {
    const PLAN = {
      week_label: "8/29 〜 9/5",
      counts: { total: 2, selected: 2 },
      files: [{
        nickname: "視聴者A🐢💤", user_unique_id: "viewer_a", identity_key: "k1", rank: 1,
        position: 1, coin: 13543, diamonds: 10999, seconds: 18.0,
        filename: EXPORT_FILE, count: 2,
        items: [
          { start: 12.0, end: 21.0, highlight_id: 7, at: 14.5, segment_id: 101,
            gift_name: "Goal Highlight", diamonds: 6000, identity_key: "k1",
            user_nickname: "視聴者A🐢💤", confidence: "high", approved: true },
          { start: 45.0, end: 54.0, highlight_id: 8, at: 47.2, segment_id: 401,
            gift_name: "Guardian's Pledge", diamonds: 4999, identity_key: "k1",
            user_nickname: "視聴者A🐢💤", confidence: "high", approved: true },
        ],
        cuts: [
          { start: 12.0, end: 21.0, seconds: 9.0, highlight_id: 7, diamonds: 6000,
            gifts: [{ gift_event_id: 900, gift_name: "Goal Highlight",
                      diamonds: 6000, user_nickname: "視聴者A🐢💤" }] },
          // **別の素材から来る窓。** 1本のfileは複数のハイライトに跨る。
          { start: 45.0, end: 54.0, seconds: 9.0, highlight_id: 8, diamonds: 4999,
            gifts: [{ gift_event_id: 904, gift_name: "Guardian's Pledge",
                      diamonds: 4999, user_nickname: "視聴者A🐢💤" }] },
        ],
      }],
      skipped: [],
    };
    const MEDIA_8 = "/api/highlights/8/media";
    const TWO_SOURCES = {
      items: [HIGHLIGHTS[0],
              { ...HIGHLIGHTS[0], id: 8, filename: "g65hl0000005.mp4",
                url: MEDIA_8 }],
      defaults: DEFAULTS, upload_dirs: { [STREAMER]: UPLOAD_DIR },
    };

    async function planned(over = {}) {
      await open({ "POST /api/highlights/export/plan": PLAN,
                   [`GET ${URL_LIST}`]: TWO_SOURCES, ...over },
                 { playable: true });
      doc.getElementById("tab-export").click();
      await page.settle();
    }

    const chapters = () => Array.from(doc.querySelectorAll("#ex-chapters .st-chapter"));
    // 窓の終わりまで進んだことにする。jsdom は再生しないので、時刻を進めて
    // timeupdate を自分で起こす。
    const advanceTo = async (at) => {
      const video = doc.getElementById("ex-video");
      video.currentTime = at;
      video.dispatchEvent(new win.Event("timeupdate"));
      await page.settle();
      video.dispatchEvent(new win.Event("loadedmetadata"));
      await page.settle();
    };

    it("下見の束を、繋ぐ順に通して観られる(素材を跨いでも続く)", async () => {
      await planned();
      const through = Array.from(rows("ex-rows")[0].querySelectorAll(".st-playbtn"))
        .find((b) => b.textContent === "通し");
      expect(through.disabled).toBe(false);
      through.click();
      await page.settle();

      // 章の帯が窓の並びそのものになる。**giftの件数ではなく窓の数**である。
      expect(chapters().map((c) => c.textContent))
        .toEqual(["1Goal Highlight🪙6k / 9.0秒",
                  "2Guardian's Pledge🪙5k / 9.0秒"]);
      const video = doc.getElementById("ex-video");
      expect(video.getAttribute("src")).toBe(MEDIA_7);
      video.dispatchEvent(new win.Event("loadedmetadata"));
      expect(video.currentTime).toBeCloseTo(12.0, 3);
      expect(chapters()[0].classList.contains("st-chapter-now")).toBe(true);
      expect(doc.getElementById("ex-run-note").textContent).toContain("1/2");

      // 1つめの窓の終わりまで来たら、**別の素材へ移って**続きを流す。
      await advanceTo(21.0);
      expect(video.getAttribute("src")).toBe(MEDIA_8);
      expect(video.currentTime).toBeCloseTo(45.0, 3);
      expect(chapters()[1].classList.contains("st-chapter-now")).toBe(true);
      expect(doc.getElementById("ex-run-note").textContent).toContain("2/2");

      // 最後まで来たら止まる。**次の窓(=無関係な場面)へ流れ込ませない。**
      await advanceTo(54.0);
      expect(doc.getElementById("ex-run-note").textContent).toContain("終わり");
      expect(doc.getElementById("ex-play-stop").disabled).toBe(true);
    });

    it("繋ぎ目だけを流せる(不具合は必ず繋ぎ目に出る)", async () => {
      await planned();
      Array.from(rows("ex-rows")[0].querySelectorAll(".st-playbtn"))
        .find((b) => b.textContent === "通し").click();
      await page.settle();
      doc.getElementById("ex-play-joins").click();
      await page.settle();
      const video = doc.getElementById("ex-video");
      video.dispatchEvent(new win.Event("loadedmetadata"));
      // 1つめの窓の**尻**から。ここに前の場面が残っていないかを見る。
      expect(video.currentTime).toBeCloseTo(21.0 - 1.5, 3);
      expect(doc.getElementById("ex-run-note").textContent).toContain("1→2本目");

      await advanceTo(21.0);
      // 素材が変わるので繋がず、2つめの窓の**頭**から流す。
      expect(video.getAttribute("src")).toBe(MEDIA_8);
      expect(video.currentTime).toBeCloseTo(45.0, 3);
      await advanceTo(46.5);
      expect(doc.getElementById("ex-run-note").textContent).toContain("繋ぎ目 終わり");
    });

    it("窓が1つだけの束では、繋ぎ目が無いことを言う", async () => {
      const single = { ...PLAN,
                       files: [{ ...PLAN.files[0], cuts: [PLAN.files[0].cuts[0]] }] };
      await planned({ "POST /api/highlights/export/plan": single });
      Array.from(rows("ex-rows")[0].querySelectorAll(".st-playbtn"))
        .find((b) => b.textContent === "通し").click();
      await page.settle();
      // 窓が1つなら繋ぎ目は無い。**押せない形で名乗る**(押しても何も起きない、にしない)。
      expect(doc.getElementById("ex-play-joins").disabled).toBe(true);
      expect(doc.getElementById("ex-play-all").disabled).toBe(false);
    });

    it("素材の再生URLが1つでも無ければ、通しでは出さない", async () => {
      // 流せる分だけを繋ぐと、抜けたまま観た物が「出来上がり」として読まれる ——
      // 抜けたことは画面のどこにも出ない。
      await planned({ [`GET ${URL_LIST}`]: {
        items: [HIGHLIGHTS[0]], defaults: DEFAULTS } });
      const through = Array.from(rows("ex-rows")[0].querySelectorAll(".st-playbtn"))
        .find((b) => b.textContent === "通し");
      // 押せないことはbuttonそのものが名乗る(理由の文言は置かない)。
      expect(through.disabled).toBe(true);
      expect(through.title).toBe("");
    });

    it("書き出し済みのfileにも章が出る(素性から引く)", async () => {
      await open({}, { playable: true });
      doc.getElementById("tab-export").click();
      await page.settle();
      doc.querySelectorAll("#ex-files .st-filepick")[0].click();
      await page.settle();
      // 繋ぎ目はmp4の中に印が無い。**素性のJSONだけが窓の並びを持つ。**
      expect(chapters().length).toBe(2);
      expect(chapters()[1].textContent).toContain("Guardian's Pledge");
      // 1本のfileなので、章はその中の位置(累計)である。
      Array.from(doc.querySelectorAll("#ex-chapters .st-chapter"))[1].click();
      await page.settle();
      const video = doc.getElementById("ex-video");
      video.dispatchEvent(new win.Event("loadedmetadata"));
      expect(video.getAttribute("src")).toBe(EXPORTS.items[0].url);
      expect(video.currentTime).toBeCloseTo(9.0, 3);
    });

    it("素性が無いfileは章を出さず、理由を名乗る(再生は止めない)", async () => {
      await open({
        [`GET ${URL_PROVENANCE}`]: { streamer: STREAMER, filename: EXPORT_FILE,
                                     provenance: false, cuts: [] },
      }, { playable: true });
      doc.getElementById("tab-export").click();
      await page.settle();
      doc.querySelectorAll("#ex-files .st-filepick")[0].click();
      await page.settle();
      expect(chapters().length).toBe(0);
      expect(doc.getElementById("ex-run-note").textContent).toContain("素性");
      // **再生そのものは成り立つ。**
      expect(doc.getElementById("ex-video").getAttribute("src"))
        .toBe(EXPORTS.items[0].url);
    });
  });

  // ===== 投入(画面へdropして置き場へ入れる) =====
  // 置き場は**配信者folderの下**に在る。ここまでは利用者がfolderを開いて正しい配信者の下へ
  // 手でfileを置き、それから「置き場を走査」を押していた。置き場を間違えたハイライトは
  // 失敗として現れず、その人の週のgiftと突き合わせて「当たらない」だけになる ——
  // だから縛るのは「**どこへ入るのかが落とす前に読めること**」と「投入先が決まらないなら
  // 受けないこと」、そして「断ったfileの理由が1件ずつ出ること」である。
  // 一覧tabは「載せて照合を起動する場所」であると同時に、**要らない行を片付ける場所**でも
  // ある。走査は実体の消えたfileの行を消さずに「fileが無い」へ倒す(置き場が一時的に
  // 外れているだけのことがあり、照合結果と人の手直しを道連れにできない)ので、
  // **戻ってこないfileの行は誰かが外さない限り溜まり続ける。**
  //
  // 外す道そのものは前からあったが、そこへ辿り着けなかった —— 行をclickすると検証tabへ
  // 飛ばされるため、選択の列を押し損ねるたびに面が入れ替わり、一覧の位置も選択も失われた。
  // **確かめる場所を一覧と同じ面に置く**(左paneのplayer)のが検証・出力と同じ約束である。
  describe("要らない行を片付ける", () => {
    const GONE = {
      id: 3, unique_id: STREAMER, filename: "synth_1153_0.mp4",
      path: "D:/rec/streamer_a/highlights/synth_1153_0.mp4",
      // 実体が無い行にServerは再生URLを返さない(``_with_url``)。押しても404になる
      // buttonを出さないための取り決めで、画面はpathからURLを組み立てない。
      url: null,
      duration_seconds: 10.0, status: "missing", segment_count: 0,
      top_diamonds: 0, total_diamonds: 0, matched_at: null,
    };

    const withGone = (over = {}) => ({
      [`GET ${URL_LIST}`]: { items: [...HIGHLIGHTS, GONE], defaults: DEFAULTS,
                             upload_dirs: { [STREAMER]: UPLOAD_DIR } },
      ...over,
    });

    const listRow = (name) =>
      rows("hl-rows").find((tr) => tr.textContent.includes(name));
    const deletes = () =>
      page.calls.fetches.filter((f) => f.method === "DELETE");
    const confirmRun = async () => {
      doc.querySelector(".confirm-modal .btn-danger").click();
      await page.settle();
    };

    it("実体の無い行は一覧に残り、片付ける道が件数つきで出る", async () => {
      // 隠さない。**行が在ることが読めて初めて片付けられる** —— 黙って落とすと、
      // 置き場が一時的に外れただけの行まで見えなくなる。
      await open(withGone());
      expect(listRow("synth_1153_0.mp4")).toBeTruthy();
      const purge = doc.getElementById("hl-purge");
      expect(purge.classList.contains("hidden")).toBe(false);
      expect(purge.textContent).toBe("✕ 1");
    });

    it("実体の無い行が無ければ、片付けるbuttonは出さない", async () => {
      // 常設にすると、出ているのが普通の帯になって目に入らなくなる。
      await open();
      expect(doc.getElementById("hl-purge").classList.contains("hidden")).toBe(true);
    });

    it("片付けは確認を挟んでから、その行だけをDELETEする", async () => {
      await open(withGone({ "DELETE /api/highlights/3": { deleted: true } }));
      doc.getElementById("hl-purge").click();
      await page.settle();
      const modal = doc.querySelector(".confirm-modal");
      expect(modal).toBeTruthy();
      // 何を消すのかをfile名で名乗る(件数だけでは、どの行が消えるのか判らない)。
      expect(modal.textContent).toContain("synth_1153_0.mp4");
      await confirmRun();
      expect(deletes().map((f) => f.url)).toEqual(["/api/highlights/3"]);
      // 台帳は引き直す。引き直さないと、消したのに一覧へ残ったままになる。
      expect(page.calls.fetches.filter((f) => f.url === URL_LIST).length).toBe(2);
    });

    it("片付けは絞り込みの外の行も対象にする", async () => {
      // 溜まった物を片付けるための操作なので、今どの状態で絞っているかとは関係が無い。
      await open(withGone({ "DELETE /api/highlights/3": { deleted: true } }));
      const status = doc.getElementById("hl-status");
      status.value = "matched";
      status.dispatchEvent(new win.Event("change", { bubbles: true }));
      await page.settle();
      expect(listRow("synth_1153_0.mp4")).toBeFalsy();
      expect(doc.getElementById("hl-purge").classList.contains("hidden")).toBe(false);
      doc.getElementById("hl-purge").click();
      await page.settle();
      await confirmRun();
      expect(deletes().map((f) => f.url)).toEqual(["/api/highlights/3"]);
    });

    it("外せなかった行は理由を出す(「n本外しました」で黙らせない)", async () => {
      await open(withGone({
        // jsdomはfetch/Responseを持たないので、**window側ではなくNodeのResponse**を返す
        // (win.Response は undefined で、触ると「Serverへ接続できませんでした」の経路に
        //  化ける ―― 出したいのはHTTPの失敗である)。
        "DELETE /api/highlights/3": () =>
          new Response(JSON.stringify({ detail: "使用中です。" }),
            { status: 409, headers: { "Content-Type": "application/json" } }),
      }));
      doc.getElementById("hl-purge").click();
      await page.settle();
      await confirmRun();
      expect(doc.body.textContent).toContain("使用中です。");
    });

    it("選んで消す道でも、選択の列を押した時に面が動かない", async () => {
      // checkboxそのものは小さい。その周りのcellを押した時に別の面へ飛ぶと、選ぼうと
      // した操作が「面の移動」に化け、選び直すたびに一覧の位置が失われる。
      await open(withGone({ "DELETE /api/highlights/3": { deleted: true } }));
      const tr = listRow("synth_1153_0.mp4");
      tr.cells[0].click();
      await page.settle();
      expect(doc.getElementById("view-list").classList.contains("hidden")).toBe(false);
      expect(doc.getElementById("hl-delete").disabled).toBe(false);
      doc.getElementById("hl-delete").click();
      await page.settle();
      await confirmRun();
      expect(deletes().map((f) => f.url)).toEqual(["/api/highlights/3"]);
    });
  });

  // 一覧tabの左pane。**行をclickしても面は動かない。**
  describe("一覧の行を左のpaneで観る", () => {
    const listRow = (name) =>
      rows("hl-rows").find((tr) => tr.textContent.includes(name));

    it("行をclickすると左のplayerに載り、面は動かない", async () => {
      await open();
      listRow("g65hl0000001.mp4").click();
      await page.settle();
      // Serverが名乗ったURLをそのまま使う(画面はpathからURLを組み立てない)。
      expect(doc.getElementById("hl-video").getAttribute("src")).toBe(MEDIA_7);
      // 動画の上に名乗りの段は置かない。**押した行そのものに印が付く**(検証・出力と同じ)。
      expect(doc.getElementById("hl-play-head")).toBeNull();
      expect(listRow("g65hl0000001.mp4").classList.contains("st-current")).toBe(true);
      // tabは一覧のまま。以前は検証tabへ飛ばしていた。
      expect(doc.getElementById("view-list").classList.contains("hidden")).toBe(false);
      expect(doc.getElementById("view-cover").classList.contains("hidden")).toBe(true);
    });

    it("実体の無い行では再生を起こさず、理由を名乗る", async () => {
      // 押しても404になるだけの再生は起こさない。**なぜ出せないのか**が読めて初めて、
      // 片付けるという次の操作に繋がる。
      await open({
        [`GET ${URL_LIST}`]: {
          items: [{ id: 3, unique_id: STREAMER, filename: "synth_1153_0.mp4",
                    path: "D:/rec/streamer_a/highlights/synth_1153_0.mp4", url: null,
                    duration_seconds: 10.0, status: "missing", segment_count: 0 }],
          defaults: DEFAULTS, upload_dirs: { [STREAMER]: UPLOAD_DIR },
        },
      });
      listRow("synth_1153_0.mp4").click();
      await page.settle();
      expect(doc.getElementById("hl-video").getAttribute("src")).toBeNull();
      expect(doc.getElementById("hl-play-status").textContent).toBe("fileが無い");
    });

    // 行の操作は「照合」だけである。隣に在った「検証」は**行の主語と移る先の主語が違った**
    // —— 押した1本ではなく、その配信者の週ぜんたいの面へ飛ぶbuttonが行ごとに並んでいた
    // ので、押した本と出てくる物が結び付かない(利用者の指定で外した)。検証の面へは
    // 上のtabから移る。
    it("行のbuttonは照合だけで、面を移るbuttonは置かない", async () => {
      await open();
      const labels = Array.from(listRow("g65hl0000001.mp4").querySelectorAll("button"))
        .map((el) => el.textContent);
      expect(labels).toEqual(["照合"]);
    });
  });

  describe("ハイライトの投入", () => {
    const UPLOAD_URL = "/api/highlights/upload";
    const NEW_FILE = "g65hl0000005.mp4";

    function uploaded(over = {}) {
      return {
        streamer: STREAMER, directory: UPLOAD_DIR, saved: 1, rejected: 0,
        items: [{ filename: NEW_FILE, saved: true, reason: "", bytes: 1234,
                  path: `${UPLOAD_DIR}/${NEW_FILE}` }],
        scan: { added: 1, updated: 0, missing: 0, dirs: [{ path: UPLOAD_DIR }] },
        ...over,
      };
    }

    // fileのdrag。jsdomは DataTransfer を持たないので、画面が実際に読む物
    // (types / files / dropEffect)だけを持つ物を載せる。
    function fileDrag(type, target, files) {
      const ev = new win.Event(type, { bubbles: true, cancelable: true });
      Object.defineProperty(ev, "dataTransfer", {
        value: { types: ["Files"], files: files || [], dropEffect: "" },
      });
      target.dispatchEvent(ev);
      return ev;
    }

    const mp4 = (name, body = "mp4-bytes") =>
      new win.File([body], name, { type: "video/mp4" });

    async function dropOn(id, files) {
      const target = doc.getElementById(id);
      fileDrag("dragover", target, files);
      const ev = fileDrag("drop", target, files);
      await page.settle();
      return ev;
    }

    async function pickStreamer(name) {
      const button = Array.from(doc.querySelectorAll("#hl-streamers .vd-group-pick"))
        .find((el) => el.textContent.includes(name));
      button.click();
      await page.settle();
    }

    const uploads = () => page.calls.fetches.filter((f) => f.url === UPLOAD_URL);
    const listCalls = () =>
      page.calls.fetches.filter((f) => f.url === URL_LIST).length;

    it("配信者が「全て」のままでは受けず、何をすればよいかを名乗る", async () => {
      // 置き場が配信者folderの下に在る以上、投入先が決まらない。適当な場所へ置くと、
      // そのハイライトは別人の週のgiftと突き合わせられて当たらないだけで、失敗として
      // 見えない。
      await open({ [`POST ${UPLOAD_URL}`]: uploaded() });
      expect(doc.getElementById("hl-streamers").textContent).toContain("全て");
      await dropOn("view-list", [mp4(NEW_FILE)]);
      expect(uploads().length).toBe(0);
      expect(doc.body.textContent).toContain("配信者を選んでください");
    });

    it("dragの間に、投入先のpathと配信者を名乗る", async () => {
      // **どこへ入るのか判らないまま落とさせない。** pathはServerが名乗った値をそのまま
      // 出す(画面では組み立てない)。
      await open();
      await pickStreamer(STREAMER);
      fileDrag("dragover", doc.getElementById("hl-rows"), [mp4(NEW_FILE)]);
      const hint = doc.getElementById("hl-drop");
      expect(hint.classList.contains("hidden")).toBe(false);
      expect(hint.classList.contains("st-drop-blocked")).toBe(false);
      const where = doc.getElementById("hl-drop-where").textContent;
      expect(where).toContain(STREAMER);
      expect(where).toContain(UPLOAD_DIR);
    });

    it("受けられないときは、dragの時点でそう名乗る", async () => {
      // 落としてから断るのでは遅い。受けられない印(st-drop-blocked)を出して理由を書く。
      await open();
      fileDrag("dragover", doc.getElementById("hl-rows"), [mp4(NEW_FILE)]);
      expect(doc.getElementById("hl-drop").classList.contains("st-drop-blocked"))
        .toBe(true);
      expect(doc.getElementById("hl-drop-where").textContent).toContain("配信者");
    });

    it("配信者を選んでいれば、その配信者で投入する", async () => {
      await open({ [`POST ${UPLOAD_URL}`]: uploaded() });
      await pickStreamer(STREAMER);
      await dropOn("view-list", [mp4(NEW_FILE), mp4("g65hl0000001.mp4")]);

      const [call] = uploads();
      expect(call.method).toBe("POST");
      // 配信者はbodyで名乗る(投入先を決めるのはServerで、画面はpathを組み立てない)。
      expect(call.body.get("streamer")).toBe(STREAMER);
      expect(call.body.getAll("files").map((f) => f.name))
        .toEqual([NEW_FILE, "g65hl0000001.mp4"]);
      // 何件入ったかと、どこへ入ったかを名乗る。
      const text = doc.body.textContent;
      expect(text).toContain("+1");
      expect(text).toContain(UPLOAD_DIR);
    });

    it("投入が終わったら台帳を引き直す", async () => {
      // 台帳はServerが走査して作る。引き直さないと、投入したのに一覧に出ない。
      await open({ [`POST ${UPLOAD_URL}`]: uploaded() });
      await pickStreamer(STREAMER);
      const before = listCalls();
      await dropOn("view-list", [mp4(NEW_FILE)]);
      expect(listCalls()).toBe(before + 1);
    });

    it("断られたfileは1件ずつ理由を出す", async () => {
      // まとめて「n件失敗」にすると、どれがなぜ入らなかったのかが判らず、利用者は
      // もう一度全部を落とすしかなくなる。
      await open({ [`POST ${UPLOAD_URL}`]: uploaded({
        saved: 1, rejected: 2,
        items: [
          { filename: NEW_FILE, saved: true, reason: "", bytes: 1234,
            path: `${UPLOAD_DIR}/${NEW_FILE}` },
          { filename: "thumb.jpg", saved: false,
            reason: "扱えるのは .mp4 だけです: thumb.jpg", bytes: null, path: null },
          { filename: "old.mp4", saved: false,
            reason: "同じ内容のfileが既にあるので置き換えませんでした。",
            bytes: 99, path: `${UPLOAD_DIR}/old.mp4` },
        ],
      }) });
      await pickStreamer(STREAMER);
      await dropOn("view-list", [mp4(NEW_FILE)]);

      const text = doc.body.textContent;
      expect(text).toContain("thumb.jpg");
      expect(text).toContain("扱えるのは .mp4 だけです");
      expect(text).toContain("old.mp4");
      expect(text).toContain("同じ内容のfileが既にある");
      // 入った物と入らなかった物を両方名乗る(片方だけだと結末が読めない)。
      expect(doc.getElementById("hl-status-note").textContent).toContain("+1");
      expect(doc.getElementById("hl-status-note").textContent).toContain("✕2");
    });

    it("ハイライト一覧tab以外へ落ちた物は投入しない", async () => {
      // 検証tab・出力tabへ落とした物を黙って投入すると、見ている面と関係の無い所で
      // fileが増える。ただしbrowserが動画を開いてしまうのは面の外でも止める。
      await openCover({ [`POST ${UPLOAD_URL}`]: uploaded() });
      const ev = await dropOn("view-cover", [mp4(NEW_FILE)]);
      expect(uploads().length).toBe(0);
      expect(ev.defaultPrevented).toBe(true);
    });

    it("buttonからも同じことができる(dropだけにしない)", async () => {
      // dropはtouchやキー操作の利用者には使えない操作である。
      await open();
      const input = doc.getElementById("hl-file");
      expect(input.multiple).toBe(true);
      let opened = 0;
      input.addEventListener("click", () => { opened += 1; });
      doc.getElementById("hl-add").click();
      expect(opened).toBe(1);
    });
  });

  // ===== 時間軸(seek bar) =====
  //
  // **配信者動画のbarと同じ手つきでなければならない。** 同じ作業(再生位置を掴む・範囲の端を
  // 詰める・その瞬間に何が飛んだかを見る)を2つの画面で行うので、掴める場所が食い違うと
  // 「線の上を掴んだのにseekした」が片方だけで起きる。描画そのものは共通(timeline.js)だが、
  // **何を載せるか**と**どこまで動かせるか**はこの画面が決めるので、そこを縛る。
  describe("時間軸", () => {
    // jsdomはlayoutを持たないので、canvasの実寸はtestが与える(0だと軸が開かない)。
    function sizeCanvas(id, width, height) {
      const canvas = doc.getElementById(id);
      Object.defineProperty(canvas, "clientWidth", { configurable: true, get: () => width });
      Object.defineProperty(canvas, "clientHeight", { configurable: true, get: () => height });
      return canvas;
    }

    // 掴む相手はその行の区間なので、行を1つ選んでから見る。
    async function openBar(text = "Guardian's Pledge") {
      await openCover({}, { playable: true });
      await selectRow(text);
      sizeCanvas("cv-timeline", 600, 160);
      return win.barGeometry("cv-timeline");
    }

    // pointerの位置を秒で指す。yはbarの上端からのpx。
    const hitAt = (geo, seconds, y, bar = "cv-timeline") =>
      win.hitTestBar(bar, { clientX: geo.xOf(seconds), clientY: y, pointerType: "mouse" });

    it("区間の端は帯の全高で掴める(線の上を掴んでseekしない)", async () => {
      const geo = await openBar();
      const cut = win.editingCut();
      expect(hitAt(geo, cut.start, 3)).toBe("in");
      expect(hitAt(geo, cut.end, 3)).toBe("out");
      // 上端laneの外でも掴める。線は全高に描いてあるので、laneの中だけだと掴み損ねる。
      expect(hitAt(geo, cut.start, 80)).toBe("in");
      expect(hitAt(geo, cut.end, 80)).toBe("out");
    });

    it("上端laneの帯の中は平行移動、それ以外はseek", async () => {
      const geo = await openBar();
      const cut = win.editingCut();
      const middle = (cut.start + cut.end) / 2;
      expect(hitAt(geo, middle, 3)).toBe("band");
      expect(hitAt(geo, middle, 80)).toBe("seek");
      // 範囲の外は上端laneでもseek(**範囲の新規作成は無い** —— giftごとに区間は必ず在る)。
      expect(hitAt(geo, 0.5, 3)).toBe("seek");
    });

    // **軸は1本だけである。** 以前はこの下にgift演出±2秒だけを映す拡大軸がもう1本在ったが、
    // ハイライトは実測でほとんどが1分前後で、横いっぱいへ移した今の軸は1pxが0.05秒しか
    // 無い —— 同じ物を2本並べる理由が無くなった(利用者の指定)。
    it("軸は1本だけ(拡大軸は畳んだ)", async () => {
      const geo = await openBar();
      expect(doc.getElementById("cv-zoom")).toBe(null);
      expect(geo).toBeTruthy();
    });

    // 拡大軸だけが持っていた2つ ―― 「映像が切り替わり終わる秒」と「同じgift演出に載る他の人の
    // gift」―― は、選んでいるgift演出の枠の中へ移した。**落とすと、窓がgift演出の境目とずれている
    // 理由も、他人のfileが隣に在ることも読めなくなる。**
    it("選んでいるgift演出の中に、映像の切り替わりと他の人のgiftを出す", async () => {
      // 1つのgift演出にgiftが3件載る形(連投)に、映像の切り替わりを足したもの。**尺の中の
      // gift演出を使う** —— 尺の外のgift演出はtoXが端で止めるので、位置の確かめにならない。
      const seg = {
        ...SEGMENTS[5], video_start: 54.6, video_probed: true,
        gifts: [SEGMENTS[5].gifts[0],
                { ...SEGMENTS[5].gifts[1], cut_start: 57.0, cut_end: 60.0, cut_own: true },
                SEGMENTS[5].gifts[2]],
      };
      await openCover({ [`GET ${URL_DETAIL}`]: {
        highlight: HIGHLIGHTS[0],
        segments: [...SEGMENTS.slice(0, 5), seg, ...SEGMENTS.slice(6)],
      } }, { playable: true });
      await selectRow("Rose");
      const canvas = sizeCanvas("cv-timeline", 600, 160);
      const ctx = canvas.getContext("2d");
      ctx.__ops.length = 0;
      win.drawTimeline();
      const duration = win.timelineDuration();
      const toX = (t) => (t / duration) * 600;
      // 映像の切り替わりは刻み(幅2・高さ3)の縦線で立つ。
      const dashes = ctx.__ops
        .filter(([name, , , w, h]) => name === "fillRect" && w === 2 && h === 3)
        .map(([, x]) => x + 1);
      expect(dashes.length).toBeGreaterThan(0);
      dashes.forEach((x) => expect(Math.abs(x - toX(54.6))).toBeLessThan(1.5));
      // 同じgift演出の他の1件の区間は薄い帯で出る。**選んでいる1件は帯にしない**(枠で出る)。
      const band = ctx.__ops.filter(([name, x, , w]) => name === "fillRect"
        && Math.abs(x - toX(57.0)) < 1 && Math.abs(w - (toX(60.0) - toX(57.0))) < 1);
      expect(band.length).toBe(1);
    });

    it("区間はgift演出の外へ出せない(外はまったく無関係な場面である)", async () => {
      const geo = await openBar();
      expect(win.clampToSegment(geo, geo.low - 5)).toBe(geo.low);
      expect(win.clampToSegment(geo, geo.high + 5)).toBe(geo.high);
    });

    it("軸に載せるのは位置とiconの両方が在るgiftだけ", async () => {
      await openBar();
      const names = win.timelineGifts().map((gift) => gift.gift_name);
      // 位置(at)を出せないgiftをgift演出の頭で代用すると、判っていない位置が判っているように
      // 並ぶ。iconを出せないgiftは場所だけ取って絵の出ない枠になり、隣のgiftを落とす。
      expect(names).toContain("Guardian's Pledge");
      expect(win.timelineGifts().every((gift) => win.num(gift.at) !== null)).toBe(true);
      expect(win.timelineGifts().every(
        (gift) => String(gift.gift_image || "").startsWith("/"))).toBe(true);
    });

    // ===== 軸の下へ敷くコマ(filmstrip) =====
    //
    // gift演出の境目は**音**で決まっていて、映像はそこから遅れて切り替わる。どこで切り替わり
    // 終わるのかは、再生しない限り読めなかった —— それを目で追わせるために動画のコマを
    // 敷く。Serverが焼いた1枚のsprite sheetを使い回す(1枚ずつのfileで敷くと、軸1本を
    // 描くのに数十のHTTP往復が要る)。
    //
    // **置き場所は軸の地ではなく軸の下の帯である。** 地へ敷くと、同じ場所に載るgiftの
    // iconと名前が絵に紛れて読めなかった(利用者の指摘)。
    const STRIP = {
      highlight_id: 7, count: 240, columns: 16, rows: 15, interval_seconds: 0.25,
      tile_width: 80, tile_height: 142, duration_seconds: 60,
      url: "/api/highlights/7/thumbnails.jpg?v=strip_abc123_w80_s250ms",
    };

    // jsdomのImageは実際には読まない。**読めた物として**扱わせる —— 画面は
    // complete/naturalWidth でしか「敷ける絵か」を判っていないので、そこだけ本物にする。
    function stubImage(win_) {
      win_.Image = class {
        constructor() {
          this.complete = false;
          this.naturalWidth = 0;
          this._onload = [];
        }
        addEventListener(name, fn) { if (name === "load") this._onload.push(fn); }
        set src(value) {
          this._src = value;
          this.complete = true;
          this.naturalWidth = 1280;
          Promise.resolve().then(() => this._onload.forEach((fn) => fn()));
        }
        get src() { return this._src; }
      };
    }

    async function openStrip(over = {}) {
      await openCover({ [`GET ${URL_DETAIL}/thumbnails`]: STRIP, ...over },
                      { playable: true });
      stubImage(win);
      await selectRow("Guardian's Pledge");
      sizeCanvas("cv-timeline", 600, 160);
      win.drawTimeline();
      // 秒はこの画面が名乗る尺で写す。fixtureの数を書き写すと、尺の出所が変わった日に
      // testだけが古い軸のまま通る。
      const duration = win.timelineDuration();
      return doc.getElementById("cv-timeline").getContext("2d").__ops
        .filter(([name, image]) => name === "drawImage"
          && String((image && image.src) || "").includes("thumbnails.jpg"))
        .map(([, , sx, sy, , , dx, , dw]) => ({
          index: (sy / STRIP.tile_height) * STRIP.columns + sx / STRIP.tile_width,
          at: ((dx + dw / 2) / 600) * duration,
        }));
    }

    it("軸の下の帯に動画のコマを敷く(その秒**以前**のtileを選ぶ)", async () => {
      const tiles = await openStrip();
      expect(tiles.length).toBeGreaterThan(1);
      tiles.forEach(({ index, at }) => {
        // 切り上げてはいけない。切り替わりの手前の枠に「切り替わった後の絵」が入ると、
        // 境目が実際より手前に在るように見える —— この軸で詰めているのはその境目である。
        const want = Math.min(STRIP.count - 1, Math.floor(at / STRIP.interval_seconds));
        expect(index).toBe(want);
      });
      // 秒の進みとtileの進みは同じ向き。逆走するなら写像が壊れている。
      tiles.forEach((tile, i) => {
        if (i) expect(tile.index).toBeGreaterThanOrEqual(tiles[i - 1].index);
      });
    });

    it("コマはgiftのiconと名前より下へ敷く(絵と字が重ならない)", async () => {
      await openStrip();
      const ops = doc.getElementById("cv-timeline").getContext("2d").__ops;
      const isTile = (image) => String((image && image.src) || "").includes("thumbnails.jpg");
      // sheetは9引数(sx,sy,sw,sh,dx,dy,dw,dh)、gift iconは5引数(x,y,w,h)で描く。
      const tileTops = ops.filter(([name, image]) => name === "drawImage" && isTile(image))
        .map((op) => op[7]);
      const iconBottoms = ops.filter(([name, image]) => name === "drawImage" && !isTile(image))
        .map((op) => op[3] + op[5]);
      const names = new Set(win.timelineGifts().map((gift) => gift.gift_name));
      const labelTops = ops.filter(([name, text]) => name === "fillText" && names.has(String(text)))
        .map((op) => op[3]);
      expect(tileTops.length).toBeGreaterThan(1);
      expect(iconBottoms.length).toBeGreaterThan(0);
      expect(labelTops.length).toBeGreaterThan(0);
      // 1枚でも重なると、そこのgift名は絵の上の字になって読めない。
      const top = Math.min(...tileTops);
      expect(top).toBeGreaterThanOrEqual(Math.max(...iconBottoms));
      expect(top).toBeGreaterThan(Math.max(...labelTops));
    });

    // 帯のぶんはcanvasへ**足す**。本体から削ると、iconの段が作れなくなって「同じ数秒に
    // 飛んだgiftが🪙の重い1件しか出ない」に戻る。足す量はCSSではなく画面が渡す。
    // 渡す先は**軸の枠(.st-axis)**である —— 面が縦に足りないときに軸を薄くする下限を、
    // canvasと間の受け皿(.vd-heat-wrap)が同じ値で持つ必要がある(canvasへ直に書くと
    // 受け皿から読めない)。
    it("帯のぶんだけ軸を厚くする(コマを切れば元の厚みへ戻る)", async () => {
      await openStrip();
      const axis = doc.getElementById("cv-timeline").closest(".st-axis");
      const lane = Number.parseFloat(axis.style.getPropertyValue("--strip-lane"));
      expect(lane).toBeGreaterThan(0);
      doc.getElementById("cv-show-strip").checked = false;
      doc.getElementById("cv-show-strip").dispatchEvent(new win.Event("change"));
      expect(axis.style.getPropertyValue("--strip-lane")).toBe("0px");
    });

    it("コマを消せば地は元のまま(gift演出の面と柱だけになる)", async () => {
      await openStrip();
      doc.getElementById("cv-show-strip").checked = false;
      doc.getElementById("cv-show-strip").dispatchEvent(new win.Event("change"));
      const ctx = doc.getElementById("cv-timeline").getContext("2d");
      ctx.__ops.length = 0;
      win.drawTimeline();
      expect(ctx.__ops.some(([name, image]) => name === "drawImage"
        && String((image && image.src) || "").includes("thumbnails.jpg"))).toBe(false);
    });

    it("gift演出の🪙はgiftの合計で数える(gift演出の欄は空のままなので)", async () => {
      await openBar();
      // 実データではgift演出の行の diamonds に値が入っていない(実測で全gift演出がnull)。数を
      // 持っているのはgiftの方なので、そちらから足す —— 足さないと柱が1本も立たない。
      expect(win.segmentDiamonds({ diamonds: null,
                                   gifts: [{ diamonds: 300 }, { diamonds: 300 },
                                           { diamonds: 300 }] })).toBe(900);
      expect(win.segmentDiamonds({ diamonds: 5000, gifts: [] })).toBe(0);
    });
  });
});
