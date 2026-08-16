import { describe, it, expect, afterEach } from "vitest";
import { loadPage } from "./helpers/page.js";

// 選択肢が見本画像を持つ設定(テロップpreset)。名前だけでは何が変わるか分からないので、
// server が焼いた実物を並べて選ばせる。ここが壊れると「見本が出ない」ではなく
// **選択肢そのものが出ない**(=presetを変えられない)形で失敗しうるので、画像が出せない
// ときでも選べることまで確かめる。
//
// どの設定が画像を持つかは server が option_image で決める。画面側に key を書かない
// (書くと設定を足すたびに画面も直すことになり、片方だけ古くなる)。
function settingsBody(rows) {
  return { settings: rows };
}

function styleRow(extra = {}) {
  return {
    key: "video_overlay_subtitle_style",
    value: 2,
    label: "動画化: 字幕(テロップ)の見た目",
    note: "見本は本番と同じ描画経路で焼いた実物です。",
    category: "overlay",
    category_label: "焼き込み: 表示要素と画質",
    default: 1,
    default_source: "builtin",
    builtin_default: 1,
    env: "TICTOK_VIDEO_OVERLAY_SUBTITLE_STYLE",
    min: 1,
    max: 3,
    step: 1,
    options: [
      { value: 1, label: "通常" },
      { value: 2, label: "カワイイ" },
      { value: 3, label: "ホラー" },
    ],
    option_image: "/api/settings/telop-preview/{value}.png",
    ...extra,
  };
}

function plainRow(extra = {}) {
  return {
    key: "video_overlay_subtitle_animation",
    value: 1,
    label: "動画化: 字幕の出入りの動き",
    note: "fadeとpopを付けるかどうか。",
    category: "overlay",
    category_label: "焼き込み: 表示要素と画質",
    default: 1,
    default_source: "builtin",
    builtin_default: 1,
    env: "TICTOK_VIDEO_OVERLAY_SUBTITLE_ANIMATION",
    min: 0,
    max: 1,
    step: 1,
    options: [
      { value: 0, label: "止める" },
      { value: 1, label: "付ける" },
    ],
    ...extra,
  };
}

describe("settings.js の見本つき選択肢", () => {
  let page;
  let doc;

  async function open(rows) {
    page = loadPage({
      page: "settings",
      url: "http://localhost:8520/settings",
      routes: { "GET /api/settings": settingsBody(rows) },
    });
    page.fireReady();
    await page.settle();
    doc = page.document;
  }

  afterEach(async () => {
    if (page) await page.close();
    page = null;
  });

  it("option_image を持つ設定だけが見本つきの並びになる", async () => {
    await open([styleRow(), plainRow()]);

    const galleries = doc.querySelectorAll(".option-gallery");
    expect(galleries.length).toBe(1);
    // 画像を持たない設定は従来どおりの radio のまま
    const plain = doc.querySelector(
      '.s-control input[name="video_overlay_subtitle_animation"]',
    );
    expect(plain.closest(".radio-group")).not.toBeNull();
  });

  it("選択肢ごとに value を埋めた見本画像を読む", async () => {
    await open([styleRow()]);

    const srcs = Array.from(doc.querySelectorAll(".option-card-img")).map((img) =>
      img.getAttribute("src"),
    );
    expect(srcs).toEqual([
      "/api/settings/telop-preview/1.png",
      "/api/settings/telop-preview/2.png",
      "/api/settings/telop-preview/3.png",
    ]);
    // 一覧の下の方まで一度に読みに行かない
    expect(
      Array.from(doc.querySelectorAll(".option-card-img")).every(
        (img) => img.getAttribute("loading") === "lazy",
      ),
    ).toBe(true);
  });

  it("現在値の card が選択済みで、保存はその値を送る", async () => {
    await open([styleRow()]);

    const checked = doc.querySelectorAll(
      '.option-card input[name="video_overlay_subtitle_style"]:checked',
    );
    expect(checked.length).toBe(1);
    expect(checked[0].value).toBe("2");

    doc.querySelector('.option-card input[value="3"]').checked = true;
    checked[0].checked = false;
    page.win.document.getElementById("settings-save").click();
    await page.settle();

    // 見本つきの並びも従来の radio と同じ収集経路(input[type=radio][data-key]:checked)に
    // 載る。値が文字列で載るのは既存の選択肢設定と同じで、server 側が int へ寄せる。
    const put = page.calls.fetches.find((f) => f.method === "PUT");
    expect(JSON.parse(put.body).video_overlay_subtitle_style).toBe("3");
  });

  it("見本を出せなくても label は残り、preset は選べる", async () => {
    await open([styleRow()]);

    // server が 503 を返した場合と同じ経路(img の error)
    const card = doc.querySelector(".option-card");
    const img = card.querySelector(".option-card-img");
    img.dispatchEvent(new page.win.Event("error"));

    expect(card.querySelector(".option-card-img")).toBeNull();
    expect(card.classList.contains("option-card-noimg")).toBe(true);
    expect(card.querySelector(".option-card-label").textContent).toBe("通常");
    expect(card.querySelector("input[type=radio]")).not.toBeNull();
  });

  it("「既定値へ戻す」は見本つきの並びでも効く", async () => {
    await open([styleRow()]);

    const button = Array.from(doc.querySelectorAll(".s-default button")).find(
      (b) => b.textContent === "既定値へ戻す",
    );
    button.click();

    const checked = doc.querySelector(
      '.option-card input[name="video_overlay_subtitle_style"]:checked',
    );
    expect(checked.value).toBe("1");
  });
});

// 値が文字の設定(kind=text)でも、選択肢を持つなら選ばせる。serverは選択肢の外を422で
// 拒むので、自由入力にすると「綴りを外した保存だけが失敗する」欄になる — しかも選べる
// 値の一覧は画面のどこにも出ていなかった。
describe("settings.js の文字の選択肢", () => {
  let page;

  function textChoiceRow(extra = {}) {
    return {
      key: "clip_subtitle_formats",
      value: "srt,ass",
      label: "切り出し: 字幕fileの書式",
      note: "SRTは装飾を持たず、ASSは焼き込みと同じテロップの装飾を持ちます。",
      category: "clip",
      category_label: "切り出し",
      default: "srt,ass",
      default_source: "builtin",
      builtin_default: "srt,ass",
      env: "TICTOK_CLIP_SUBTITLE_FORMATS",
      kind: "text",
      options: [
        { value: "srt", label: "SRTのみ" },
        { value: "srt,ass", label: "SRT + ASS" },
        { value: "ass", label: "ASSのみ" },
      ],
      ...extra,
    };
  }

  async function open(rows) {
    page = loadPage({
      page: "settings",
      url: "http://localhost:8520/settings",
      routes: { "GET /api/settings": settingsBody(rows) },
    });
    page.fireReady();
    await page.settle();
  }

  afterEach(async () => {
    if (page) await page.close();
    page = null;
  });

  it("選択肢を持つ文字の設定は自由入力ではなくradioで出る", async () => {
    await open([textChoiceRow()]);
    const doc = page.document;
    expect(doc.querySelector('input[type=text][data-key="clip_subtitle_formats"]')).toBeNull();
    const checked = doc.querySelectorAll('input[name="clip_subtitle_formats"]:checked');
    expect(checked.length).toBe(1);
    expect(checked[0].value).toBe("srt,ass");
  });

  it("選択肢を持たない文字の設定(保存先のpath)は今までどおり自由入力", async () => {
    await open([textChoiceRow({
      key: "record_dir", value: "K:/80_Tiktok", label: "録画の保存先",
      env: "TICTOK_RECORD_DIR", options: undefined,
    })]);
    expect(page.document.querySelector('input[type=text][data-key="record_dir"]')).not.toBeNull();
  });
});
