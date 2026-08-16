import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { loadCommon } from "./helpers/page.js";

// 表示設定の永続化。各画面は独立した document で nav 遷移がフルリロードなので、
// 並べ替え・絞り込み・表示切替は localStorage に残さないと毎回初期値へ戻る。
// ここで守りたいのは「残す」ことだけではない:
//   - 保存値の復元で onChange を呼ばない(初期 fetch と二重取得にならない)
//   - 選択肢が消えた保存値を書き込まない(select が空選択になる)
//   - storage が使えない環境でも control は動く
// どれも「画面は一見動いているのに値が壊れている」形で出るため、実 DOM で確かめる。
const HTML = `<!doctype html><html><body>
  <input type="checkbox" id="c-on" checked />
  <input type="checkbox" id="c-off" />
  <select id="s-sort">
    <option value="new">新しい順</option>
    <option value="coins">コイン順</option>
    <option value="gone" disabled>選べない</option>
  </select>
  <select id="s-late"></select>
  <input type="text" id="t-free" value="" />
  <details id="d-sec"><summary>詳細</summary></details>
  <div id="g-speed" class="seg" role="radiogroup" data-value="1">
    <button class="seg-item" type="button" data-value="0.5">0.5x</button>
    <button class="seg-item" type="button" data-value="1">1x</button>
    <button class="seg-item" type="button" data-value="2">2x</button>
  </div>
</body></html>`;

describe("表示設定の永続化 (prefGet/prefSet/restorePref/bindPref)", () => {
  let page;
  let win;
  let doc;

  beforeEach(() => {
    page = loadCommon({ html: HTML });
    win = page.win;
    doc = page.document;
    win.localStorage.clear();
  });
  afterEach(async () => page.close());

  const $ = (id) => doc.getElementById(id);
  const fire = (el, type) => el.dispatchEvent(new win.Event(type, { bubbles: true }));

  it("key は tictok. で前置し、既に前置された key は二重にしない", () => {
    win.prefSet("videos.sort", "new");
    expect(win.localStorage.getItem("tictok.videos.sort")).toBe("new");
    win.prefSet("tictok.videos.sort", "coins");
    expect(win.localStorage.length).toBe(1);
    expect(win.prefGet("videos.sort")).toBe("coins");
  });

  it("prefSet(null) は key を消す", () => {
    win.prefSet("x.y", "1");
    win.prefSet("x.y", null);
    expect(win.prefGet("x.y")).toBeNull();
  });

  it("prefBool は保存が無ければ fallback を返し、有ればそれを優先する", () => {
    expect(win.prefBool("x.none", true)).toBe(true);
    expect(win.prefBool("x.none", false)).toBe(false);
    win.prefSet("x.off", "0");
    expect(win.prefBool("x.off", true)).toBe(false);
  });

  it("checkbox は保存が無ければ markup の既定で始まり、有れば保存値で始まる", () => {
    expect(win.bindPref($("c-on"), "p.chk")).toBe(false);
    expect($("c-on").checked).toBe(true);

    $("c-on").checked = false;
    fire($("c-on"), "change");
    expect(win.prefGet("p.chk")).toBe("0");

    // 次に開いた画面(markup は checked)でも保存値の OFF が勝つ。
    const reopened = loadCommon({ html: HTML });
    reopened.win.localStorage.setItem("tictok.p.chk", "0");
    expect(reopened.win.bindPref(reopened.document.getElementById("c-on"), "p.chk")).toBe(true);
    expect(reopened.document.getElementById("c-on").checked).toBe(false);
    return reopened.close();
  });

  it("復元では onChange を呼ばず、user 操作でだけ呼ぶ(初期 fetch と二重取得にしない)", () => {
    win.prefSet("p.chk", "1");
    let hits = 0;
    win.bindPref($("c-off"), "p.chk", () => { hits += 1; });
    expect($("c-off").checked).toBe(true);
    expect(hits).toBe(0);

    fire($("c-off"), "change");
    expect(hits).toBe(1);
  });

  it("select は現存する有効な選択肢だけを復元する", () => {
    win.prefSet("p.sort", "coins");
    expect(win.bindPref($("s-sort"), "p.sort")).toBe(true);
    expect($("s-sort").value).toBe("coins");
  });

  it("消えた選択肢の保存値は無視して markup の既定を残す(空選択にしない)", () => {
    win.prefSet("p.sort", "removed-long-ago");
    expect(win.bindPref($("s-sort"), "p.sort")).toBe(false);
    expect($("s-sort").value).toBe("new");
  });

  it("disable された選択肢の保存値も復元しない", () => {
    win.prefSet("p.sort", "gone");
    expect(win.bindPref($("s-sort"), "p.sort")).toBe(false);
    expect($("s-sort").value).toBe("new");
  });

  it("選択肢を data で後から埋める select は、埋めた後の restorePref で復元できる", () => {
    win.prefSet("p.who", "bob");
    const el = $("s-late");
    // 空のうちは適用できる値が無い。ここで書き込んでしまうと選択なしになる。
    expect(win.bindPref(el, "p.who")).toBe(false);
    expect(el.value).toBe("");

    ["alice", "bob"].forEach((v) => {
      const o = doc.createElement("option");
      o.value = v;
      o.textContent = v;
      el.appendChild(o);
    });
    expect(win.restorePref(el, "p.who")).toBe(true);
    expect(el.value).toBe("bob");
  });

  it("<details> は open を toggle event で残す", () => {
    win.prefSet("p.sec", "1");
    win.bindPref($("d-sec"), "p.sec");
    expect($("d-sec").open).toBe(true);

    $("d-sec").open = false;
    fire($("d-sec"), "toggle");
    expect(win.prefGet("p.sec")).toBe("0");
  });

  it("segmented control も select と同じ I/F で残る", () => {
    const seg = win.initSegmented("g-speed");
    win.prefSet("p.speed", "2");
    expect(win.bindPref(seg, "p.speed")).toBe(true);
    expect(seg.value).toBe("2");
    // setter は user 操作ではないので change を出さない = 復元で再生設定が動かない。
    let hits = 0;
    seg.addEventListener("change", () => { hits += 1; });
    win.restorePref(seg, "p.speed");
    expect(hits).toBe(0);

    doc.querySelector('#g-speed .seg-item[data-value="0.5"]').click();
    expect(win.prefGet("p.speed")).toBe("0.5");
  });

  it("opts.event で購読する event を変えられる", () => {
    win.bindPref($("t-free"), "p.free", null, { event: "input" });
    $("t-free").value = "abc";
    fire($("t-free"), "input");
    expect(win.prefGet("p.free")).toBe("abc");
  });

  it("要素が無い画面では何もしない(共通 code を全画面で呼べる)", () => {
    expect(win.bindPref(null, "p.none")).toBe(false);
    expect(win.restorePref(undefined, "p.none")).toBe(false);
  });

  it("storage が使えなくても control は動く(保存だけを諦める)", () => {
    const broken = {
      getItem() { throw new win.Error("SecurityError"); },
      setItem() { throw new win.Error("QuotaExceededError"); },
      removeItem() { throw new win.Error("SecurityError"); },
    };
    Object.defineProperty(win, "localStorage", { configurable: true, value: broken });

    expect(() => win.bindPref($("c-on"), "p.chk")).not.toThrow();
    $("c-on").checked = false;
    expect(() => fire($("c-on"), "change")).not.toThrow();
    expect($("c-on").checked).toBe(false);
    expect(win.prefGet("p.chk")).toBeNull();
    expect(win.prefBool("p.chk", true)).toBe(true);
  });
});
