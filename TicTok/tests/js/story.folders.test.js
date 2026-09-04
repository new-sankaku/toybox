import { describe, it, expect, afterEach } from "vitest";
import { loadPage } from "./helpers/page.js";

// ハイライト一覧は**置き場のfolderで畳む**。置き場の下は利用者が作ったfolder(週ごとの
// 20260829-20260905 など)で仕分けられており、file名の平らな列では今どの週の素材を見て
// いるのかが行から読めない —— file名はTikTokのvideo idで、中身を当てられない。
//
// 縛るのは6つ。
//
// (1) 行がfolderの棚の下に並ぶこと。棚の名乗り(folderの名前・置き場・実path)はServerの
//     値で、画面がpathを組み立てないこと。
// (2) **棚が実際の入れ子のまま出ること。** folderの下のfolderは親の下へ、中身の行は親より
//     1段深く寄る —— 平らに並べると、行がどの棚の中身なのかが見た目からは読めない。
// (3) **空の棚も出ること。** かつては中身も子孫も無い棚を落としていたが、folderは
//     **投入先**でもある —— 週のfolderを作る操作と、folderの行へ動画を落とす操作を
//     持った今、作った直後の空のfolderが出ないとそこへ入れる手段が画面から消える。
// (4) 畳んでも行は対象から落ちないこと。畳むのは見た目だけで、絞り込みとは別物である。
//     親を畳めば下の棚も一緒に隠れること。
// (5) 棚のcheckboxが**そのfolderの直下の行だけ**を選ぶこと。子孫まで数えていた頃は、
//     subfolderを1つ選んだだけで上の棚まで印が付いた(置き場は直下に1本も持たず、素材が
//     全部 週のfolderの中に在るため、週を選ぶと置き場が「全選択」の見た目になっていた)。
// (6) 畳んだfolderが次に開いたときも畳んだままであること。
describe("story.js ハイライト一覧をfolderで畳む", () => {
  let page;
  let win;
  let doc;

  const STREAMER = "pomiiiip";
  const URL_LIST = "/api/highlights";
  const PLACE = `${STREAMER}/LiveHightlite`;
  const WEEK = `${PLACE}/20260829-20260905`;
  const PICKED = `${WEEK}/採用`;

  function highlight(id, over = {}) {
    return {
      id, unique_id: STREAMER, filename: `v${id}.mp4`,
      path: `D:/rec/${STREAMER}/LiveHightlite/v${id}.mp4`,
      url: `/api/highlights/${id}/media`, duration_seconds: 60.8, status: "new",
      root_key: "work", source_dir: PLACE,
      segment_count: 0, gift_segment_count: 0, gift_total_count: 0,
      top_diamonds: 0, gift_diamonds: 0, week: "", week_label: "", weeks: [],
      ...over,
    };
  }

  // 直下に1本、週のfolderに2本、その下の仕分け先に1本。もう1つの週のfolderは空
  // (素材はまだ移していない)。
  const HIGHLIGHTS = [
    highlight(1),
    highlight(2, { source_dir: WEEK, gift_total_count: 3, gift_diamonds: 6000,
                   path: `D:/rec/${STREAMER}/LiveHightlite/20260829-20260905/v2.mp4` }),
    highlight(3, { source_dir: WEEK, gift_total_count: 1, gift_diamonds: 99,
                   path: `D:/rec/${STREAMER}/LiveHightlite/20260829-20260905/v3.mp4` }),
    highlight(4, { source_dir: PICKED,
                   path: `D:/rec/${STREAMER}/LiveHightlite/20260829-20260905/採用/v4.mp4` }),
  ];

  const FOLDERS = [
    { unique_id: STREAMER, root_key: "work", source_dir: PLACE, place: PLACE,
      name: "", path: `D:/rec/${STREAMER}/LiveHightlite` },
    { unique_id: STREAMER, root_key: "work", source_dir: WEEK, place: PLACE,
      name: "20260829-20260905",
      path: `D:/rec/${STREAMER}/LiveHightlite/20260829-20260905` },
    { unique_id: STREAMER, root_key: "work", source_dir: PICKED, place: PLACE,
      name: "20260829-20260905/採用",
      path: `D:/rec/${STREAMER}/LiveHightlite/20260829-20260905/採用` },
    { unique_id: STREAMER, root_key: "work", source_dir: `${PLACE}/20260822-20260829`,
      place: PLACE, name: "20260822-20260829",
      path: `D:/rec/${STREAMER}/LiveHightlite/20260822-20260829` },
  ];

  const DEFAULTS = {
    match: { days: null, day_stages: [14, 30], scope: "gift", gift_lead: 6, gift_tail: 2,
             min_diamonds: 98, window: 5, hop: 0.128 },
    export: { order: "diamonds", pad_lead: 0.3, pad_tail: 0.5, min_diamonds: 1000 },
  };

  // 受け取れる拡張子と、作れる週のfolderの候補。**どちらもServerが名乗る** ―― 画面が
  // 拡張子の綴りや週の境目(土曜7時)を持つと、Serverの判定と2箇所に分かれる。
  const EXTENSIONS = [".mp4"];
  const WEEK_FOLDERS = [
    { name: "20260905-20260912", key: "2026-09-05",
      label: "2026-09-05 07:00 〜 2026-09-12 07:00" },
    { name: "20260829-20260905", key: "2026-08-29",
      label: "2026-08-29 07:00 〜 2026-09-05 07:00" },
  ];

  function routes(over = {}) {
    return {
      [`GET ${URL_LIST}`]: { items: HIGHLIGHTS, defaults: DEFAULTS, folders: FOLDERS,
                             extensions: EXTENSIONS, week_folders: WEEK_FOLDERS,
                             upload_dirs: { [STREAMER]: `D:/rec/${STREAMER}/highlights` } },
      ...over,
    };
  }

  async function openList(opts = {}) {
    page = loadPage({ page: "story", routes: routes(), ...opts });
    win = page.win;
    doc = page.document;
    await page.settle();
    return page;
  }

  afterEach(() => { if (page) page.close(); page = null; });

  // 表の中身を上から。棚の見出しには data-fold、素材の行には data-folder が付く。
  const shelves = () => Array.from(doc.querySelectorAll("#hl-rows tr.st-folder"));
  const shelfOf = (key) => doc.querySelector(`#hl-rows tr[data-fold="${key}"]`);
  const rowsUnder = (key) => Array.from(
    doc.querySelectorAll(`#hl-rows tr[data-folder="${key}"]`));
  // 段の深さ。字下げはcssが calc で寄せるので、画面が名乗るのはこの数だけ。
  const depthOf = (tr) => tr.style.getPropertyValue("--st-depth");

  it("行はfolderの棚の下に並び、棚の名乗りはServerの値から出る", async () => {
    await openList();
    // 置き場が先、subfolderは新しい名前が先。空のfolderもここに並ぶ(投入先として押せる
    // 必要がある)。
    expect(shelves().map((tr) => tr.querySelector("button").textContent.slice(2)))
      .toEqual([PLACE, "20260829-20260905", "採用", "20260822-20260829"]);
    // 実pathはServerが名乗った値そのまま(画面はpathを組み立てない)。
    expect(shelfOf(WEEK).querySelector("button").title)
      .toContain(`D:/rec/${STREAMER}/LiveHightlite/20260829-20260905`);
    // 週のfolderの中身は2本 + 下のfolderの1本。合計はそのfolder以下のぶんだけ。
    // 数え方の名乗りは帯の要約(#hl-summary)と揃える(本数 · gift · 🪙)。
    expect(shelfOf(WEEK).textContent).toContain("3 · 4 · 🪙6.1k");
    expect(rowsUnder(WEEK).length).toBe(2);
    expect(rowsUnder(PLACE).length).toBe(1);
    expect(rowsUnder(PICKED).length).toBe(1);
  });

  it("棚は入れ子のまま出て、中身の行は棚より1段深い", async () => {
    await openList();
    // 置き場 → 週 → 仕分け先。棚の名前は自分の段のぶんだけ(親の名前を繰り返さない)。
    expect(depthOf(shelfOf(PLACE))).toBe("0");
    expect(depthOf(shelfOf(WEEK))).toBe("1");
    expect(depthOf(shelfOf(PICKED))).toBe("2");
    // 行はその棚より1段深い。
    expect(rowsUnder(PLACE).map(depthOf)).toEqual(["1"]);
    expect(rowsUnder(WEEK).map(depthOf)).toEqual(["2", "2"]);
    expect(rowsUnder(PICKED).map(depthOf)).toEqual(["3"]);
    // 入れ子の中では置き場を繰り返さない(上の段が名乗っている)。
    expect(shelfOf(WEEK).querySelector(".st-folder-place")).toBeNull();
    // 親の数は子孫まで含む。畳んだ親が「0」と名乗ると、中に何が在るのか判らない。
    expect(shelfOf(PLACE).textContent).toContain("4 · ");
  });

  // 空のfolderも棚に出す。**投入先として押せなければ、作った意味が無い** ―― 週のfolderを
  // 作った直後は必ず空で、そこへ動画をdropするための行がこれである。中身が無いことは
  // 見出しの「0」が名乗る。
  it("素材の入っていないfolderも棚に出す(投入先として押せる)", async () => {
    await openList();
    const shelf = shelfOf(`${PLACE}/20260822-20260829`);
    expect(shelf).not.toBeNull();
    expect(shelf.querySelector(".vd-summary").textContent).toBe("0");
    // 選ぶ物が無い棚にcheckboxは出さない(押しても何も選べない印になる)。
    expect(shelf.querySelector("input[type=checkbox]")).toBeNull();
    expect(shelves().length).toBe(4);
  });

  // dropの投入先はServerが名乗った綴り(root_key + source_dir)をそのまま持ち回る。
  // 画面がpathを組み立てると、置き場の決まりが変わった日に画面だけが実在しない場所を
  // 名乗る(投入は成功するので、名乗りが嘘であることに誰も気付かない)。
  it("棚の行はdropの投入先をServerの綴りのまま持つ", async () => {
    await openList();
    const shelf = shelfOf(WEEK);
    expect(shelf.dataset.streamer).toBe(STREAMER);
    expect(shelf.dataset.rootKey).toBe("work");
    expect(shelf.dataset.fold).toBe(WEEK);
    expect(shelf.dataset.path).toBe(`D:/rec/${STREAMER}/LiveHightlite/20260829-20260905`);
  });

  it("畳むのは見た目だけで、行は選択にも件数にも残る", async () => {
    await openList();
    doc.getElementById("hl-select-all").click();
    expect(doc.getElementById("hl-selected").textContent).toBe("4");

    shelfOf(WEEK).querySelector("button").click();
    await page.settle();
    // 隠れるだけで、行そのものは表に残る。
    expect(rowsUnder(WEEK).length).toBe(2);
    expect(rowsUnder(WEEK).every((tr) => tr.classList.contains("hidden"))).toBe(true);
    // 下の棚も中身ごと隠れる。棚の見出しだけが残ると、畳んだはずの中身の在り処が並び続ける。
    expect(shelfOf(PICKED).classList.contains("hidden")).toBe(true);
    expect(rowsUnder(PICKED)[0].classList.contains("hidden")).toBe(true);
    expect(rowsUnder(PLACE)[0].classList.contains("hidden")).toBe(false);
    // 選択も要約も畳む前のまま。畳んだ拍子に選択が落ちると、選び直すために畳み直すことになる。
    expect(doc.getElementById("hl-selected").textContent).toBe("4");
    expect(doc.getElementById("hl-summary").textContent).toContain("4 · ");
  });

  // **棚のcheckboxはそのfolderの直下の行だけを相手にする。** 子孫まで数えていた頃は、
  // subfolderを1つ選んだだけで上の棚まで印が付いた —— 実測の置き場は直下に1本も持たず
  // 素材が全部 週のfolderの中に在るので、週を選ぶと置き場の棚がそのまま「全選択」の
  // 見た目になっていた(利用者の指摘)。選んでいない物へ印が付く以上、押した結果を画面
  // から読めない。
  it("棚のcheckboxはそのfolderの直下の行だけを選ぶ", async () => {
    await openList();
    shelfOf(WEEK).querySelector("input[type=checkbox]").click();
    await page.settle();
    // 直下の2本だけ。下のfolderの1本は巻き込まない。
    expect(doc.getElementById("hl-selected").textContent).toBe("2");
    expect(rowsUnder(WEEK).every(
      (tr) => tr.querySelector("input[type=checkbox]").checked)).toBe(true);
    expect(rowsUnder(PICKED)[0].querySelector("input[type=checkbox]").checked).toBe(false);
    expect(rowsUnder(PLACE)[0].querySelector("input[type=checkbox]").checked).toBe(false);
    // 自分の棚には印が付き、**上の棚には付かない**。
    expect(shelfOf(WEEK).querySelector("input[type=checkbox]").checked).toBe(true);
    expect(shelfOf(PLACE).querySelector("input[type=checkbox]").checked).toBe(false);
    expect(shelfOf(PLACE).querySelector("input[type=checkbox]").indeterminate).toBe(false);
  });

  // 逆向きも同じ。下のfolderを選んでも、上の棚は自分の直下の行だけを映す。
  it("subfolderを選んでも上の棚のcheckboxは動かない", async () => {
    await openList();
    shelfOf(PICKED).querySelector("input[type=checkbox]").click();
    await page.settle();
    expect(doc.getElementById("hl-selected").textContent).toBe("1");
    const week = shelfOf(WEEK).querySelector("input[type=checkbox]");
    const place = shelfOf(PLACE).querySelector("input[type=checkbox]");
    expect(week.checked).toBe(false);
    expect(week.indeterminate).toBe(false);
    expect(place.checked).toBe(false);
    expect(place.indeterminate).toBe(false);
  });

  it("畳んだfolderは次に開いたときも畳んだまま", async () => {
    await openList();
    shelfOf(WEEK).querySelector("button").click();
    await page.settle();
    const key = page.run("prefKey(PREF.folds)");
    expect(JSON.parse(win.localStorage.getItem(key))).toEqual([WEEK]);

    const stored = win.localStorage.getItem(key);
    page.close();
    await openList({ before: (next) => next.localStorage.setItem(key, stored) });
    expect(rowsUnder(WEEK).every((tr) => tr.classList.contains("hidden"))).toBe(true);
    expect(rowsUnder(PLACE)[0].classList.contains("hidden")).toBe(false);
  });

  // ===== folderごとの投入と、folderを作る =====
  //
  // 素材は週ごとに仕分けられている。投入した後に人が手でfileを動かしていたが、一覧には
  // 既にその棚が出ているので、**棚へ落とせれば移す手間が丸ごと消える**。folderを作る手段も
  // 画面の外(file管理画面)に在ったので、そこだけのために画面を離れることになっていた。
  describe("folderごとの投入と、週のfolderを作る", () => {
    const UPLOAD = "POST /api/highlights/upload";
    const MKDIR = "POST /api/highlights/folders";

    const uploaded = (over = {}) => ({
      streamer: STREAMER, directory: `D:/rec/${STREAMER}/highlights`,
      saved: 1, rejected: 0, items: [{ filename: "v9.mp4", saved: true, reason: "" }],
      scan: { added: 1, updated: 0, missing: 0, dirs: [] }, ...over,
    });

    const mp4 = (name) => new win.File(["mp4-bytes"], name, { type: "video/mp4" });

    // browserが渡す FileSystemEntry のうち、画面が実際に読む口だけを持つ物。
    // ``readEntries`` は**1回で全部を返さない**決まりなので、2回目に空を返す形にして、
    // 画面が空になるまで呼び続けることまで縛る。
    const fileEntry = (file) => ({
      isFile: true, isDirectory: false, name: file.name, file: (ok) => ok(file),
    });
    const dirEntry = (name, children) => ({
      isFile: false, isDirectory: true, name,
      createReader() {
        let sent = false;
        return {
          readEntries(ok) {
            ok(sent ? [] : children);
            sent = true;
          },
        };
      },
    });

    function drag(type, target, entries) {
      const ev = new win.Event(type, { bubbles: true, cancelable: true });
      Object.defineProperty(ev, "dataTransfer", {
        value: {
          types: ["Files"], files: [], dropEffect: "",
          items: entries.map((entry) => ({ kind: "file", webkitGetAsEntry: () => entry })),
        },
      });
      target.dispatchEvent(ev);
      return ev;
    }

    async function dropOn(target, entries) {
      drag("dragover", target, entries);
      drag("drop", target, entries);
      await page.settle();
    }

    const posted = (url) => page.calls.fetches.filter((f) => `${f.method} ${f.url}` === url);
    const field = (call, name) => call.body.get(name);

    async function pickStreamer() {
      const button = Array.from(doc.querySelectorAll("#hl-streamers .vd-group-pick"))
        .find((el) => el.textContent.includes(STREAMER));
      button.click();
      await page.settle();
    }

    it("folderごとdropすると、下のfolderのぶんまでmp4を拾う", async () => {
      await openList({ routes: routes({ [UPLOAD]: uploaded({ saved: 3 }) }) });
      await pickStreamer();
      // 週のfolder 1つを丸ごと落とす。中には仕分け先のfolderと、動画でないfileも在る。
      await dropOn(doc.getElementById("hl-table"), [
        dirEntry("20260829-20260905", [
          fileEntry(mp4("v9.mp4")),
          fileEntry(new win.File(["x"], "メモ.txt", { type: "text/plain" })),
          dirEntry("採用", [fileEntry(mp4("v10.mp4"))]),
        ]),
      ]);
      const call = posted(UPLOAD)[0];
      expect(call).toBeTruthy();
      expect(call.body.getAll("files").map((f) => f.name)).toEqual(["v9.mp4", "v10.mp4"]);
      // 動画でないfileは送らない。folder 1つに何十件も入っていると、1件ずつ断りが
      // 並ぶだけになる(拾う綴りはServerが名乗った extensions)。
      expect(doc.getElementById("hl-status-note").textContent).toContain("−1");
    });

    it("folderの行へ落とすと、そのfolderへ投入する", async () => {
      await openList({ routes: routes({ [UPLOAD]: uploaded() }) });
      // 配信者を選んでいなくても、行が自分の置き場を名乗っている。
      await dropOn(shelfOf(WEEK), [fileEntry(mp4("v9.mp4"))]);
      const call = posted(UPLOAD)[0];
      expect(field(call, "streamer")).toBe(STREAMER);
      // **画面はpathを組み立てない。** Serverが名乗った綴りをそのまま返す。
      expect(field(call, "root_key")).toBe("work");
      expect(field(call, "source_dir")).toBe(WEEK);
    });

    it("folderの行以外へ落とすと、配信者の置き場へ入る", async () => {
      await openList({ routes: routes({ [UPLOAD]: uploaded() }) });
      await pickStreamer();
      await dropOn(doc.getElementById("hl-table"), [fileEntry(mp4("v9.mp4"))]);
      const call = posted(UPLOAD)[0];
      expect(field(call, "streamer")).toBe(STREAMER);
      // folderを名乗らなければ、投入先はServer側が決める(置き場そのもの)。
      expect(field(call, "root_key")).toBeNull();
      expect(field(call, "source_dir")).toBeNull();
    });

    // 週のfolderの名前も候補もServerが決める。**画面で日付を組ませない** ―― 週の境目は
    // 土曜の朝7時で、画面側で組むと対象の週(検証・出力tab)と1日ずれた名前のfolderが
    // 静かに増える。
    it("作る週のfolderの候補はServerの名乗りをそのまま並べる", async () => {
      await openList();
      const select = doc.getElementById("hl-folder-week");
      expect(Array.from(select.options).map((o) => o.value))
        .toEqual(["20260905-20260912", "20260829-20260905"]);
      // 窓の端は時刻付きで名乗る(folder名の日付だけでは境目が朝7時だと読めない)。
      expect(select.options[0].title).toBe("2026-09-05 07:00 〜 2026-09-12 07:00");
      // 配信者が決まらないと作る先も決まらない。押してから断るのでは、何を直せばよいのか
      // 判らない。
      expect(doc.getElementById("hl-folder-add").disabled).toBe(true);
      await pickStreamer();
      expect(doc.getElementById("hl-folder-add").disabled).toBe(false);
    });

    it("folderを作るとServerの口へ配信者と名前だけを送る", async () => {
      await openList({
        routes: routes({
          [MKDIR]: { streamer: STREAMER, name: "20260905-20260912", created: true,
                     path: `D:/rec/${STREAMER}/highlights/20260905-20260912`,
                     source_dir: `${STREAMER}/highlights/20260905-20260912`,
                     root_key: "work" },
        }),
      });
      await pickStreamer();
      doc.getElementById("hl-folder-add").click();
      await page.settle();
      const call = posted(MKDIR)[0];
      expect(JSON.parse(call.body)).toEqual({ streamer: STREAMER, name: "20260905-20260912" });
      // 作った後は一覧を引き直す。作ったfolderが棚に出ないと、そこへ落とせない。
      expect(page.calls.fetches.filter((f) => f.url === URL_LIST).length).toBeGreaterThan(1);
    });
  });
});
