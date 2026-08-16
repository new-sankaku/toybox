(function (PF) {
'use strict';

// TODO: adult genre の行為語をここに追加する。空のままでも D1 / D3 / D4 の
// タイトル構文は属性・状況・結語だけで成立するため、app は正常に動作する。
// 語を入れると D2（状況叙述型）の展開幅が広がる。
// entry は文字列。lexicon.adult.js の他 pool と同じく重複禁止。
PF.ADULT_WORDS = {
  act: []
};

})(window.PF = window.PF || {});
