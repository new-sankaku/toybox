import { describe, it, expect, beforeEach, afterEach, vi } from "vitest";
import { loadPage } from "./helpers/page.js";

// 素材画面のタイル・種別pane・ZIPの発券。
// この画面が出す物は「diskに在る画像」そのものなので、無い物を在るように見せた瞬間に嘘になる。
// 押さえたいのは:
//   (1) cacheが無い行(cached:false)を0件として畳まず「未取得」と名乗り、選択もDownloadも
//       させない ―― 畳むと「その人のアイコンは無かった」ではなく「その人は居なかった」に読める。
//   (2) 名前を持たない素材(名前の源が無いgift/emote)に代わりの名前を作らない。
//   (3) 種別・並び順の一覧はserverの応答から作る ―― 画面が知っていると、poolへ種別が
//       増えた時に画面だけが黙って古いままになる。
//   (4) 集計していない種別(count:null)を「0件」と描かない。件数はDBのsnapshotで、
//       画面を開いても数え直さない(走査は再集計buttonだけが起こす)。
//   (5) ZIPの件数・容量は発券(POST)の応答が名乗る。件数の上限はserverのsettingsが持ち、
//       画面は上限を持たない。
//   (6) 配信者で絞れるかどうかを名乗るのはserver(kindのfilters)で、画面は種別名で
//       出し分けない。集計値(stats)も、項目・語・有無をserverが決める。
const SUMMARY = {
  pool_root: "K:\\recordings",
  // 選べる配信者はtop levelが唯一の出所。labelはunique_idと同じとは限らない。
  streamers: [
    { unique_id: "alice", label: "alice" },
    { unique_id: "bob", label: "ぼぶ" },
  ],
  kinds: [
    { kind: "gift_icon", label: "Giftアイコン", count: 3, bytes: 27800000, listable: 3,
      scanned_at: 1690000000, duration_ms: 12, filters: ["streamer"], aggregated: true,
      sorts: ["name", "size", "mtime", "sends", "coins"] },
    // listableを持たない応答でも壊れないこと(未実装・未集計のkindを想定)。
    // aggregated:false = 走査していないので集計が無い。配信者で絞ると必ず0件になるが、
    // それは「この配信者は使っていない」ではない。
    { kind: "emote", label: "Emote", count: 2, bytes: 3000000, scanned_at: 1690000000,
      duration_ms: 8, filters: ["streamer"], aggregated: false,
      sorts: ["name", "size", "mtime", "uses"] },
    // 22万件の種別。全件をscrollで眺めさせない側の代表で、diskの実数(count)より
    // 一覧に出せる数(listable)が小さい ―― 名前を辿れない素材が居る。
    { kind: "avatar", label: "Userアイコン", count: 234480, bytes: 538200000, listable: 193359,
      scanned_at: 1690000000, duration_ms: 1440, filters: ["streamer"], aggregated: true,
      sorts: ["last_seen", "name", "freq"] },
    // まだ一度も集計していない種別。0件ではない。配信者では絞れない。
    { kind: "sticker", label: "スタンプ", count: null, bytes: null, listable: null,
      scanned_at: null, duration_ms: null, filters: [], sorts: ["name"] },
    // 集計済みで本当に0件、かつ並び順をserverが出していない種別。
    { kind: "raw", label: "その他", count: 0, bytes: 0, listable: 0, scanned_at: 1690000000,
      duration_ms: 3, filters: [], sorts: [] },
  ],
};

// bootで叩くURL。並び順の既定はsummaryのsortsの先頭、向き・表示件数はmarkupの先頭option。
const GIFT_URL = "GET /api/assets?kind=gift_icon&sort=name&order=desc&limit=100&offset=0";
const AVATAR_URL = "GET /api/assets?kind=avatar&q=taro&sort=last_seen&order=desc&limit=100&offset=0";
// 並び順をserverが出していない種別へは、sort/orderを渡さない。
const RAW_URL = "GET /api/assets?kind=raw&limit=100&offset=0";
const EMOTE_URL = "GET /api/assets?kind=emote&sort=name&order=desc&limit=100&offset=0";
// 語が無いavatar。requestは出し、応答のtotalで「N件中 先頭M件」と名乗る。
const AVATAR_BROWSE_URL = "GET /api/assets?kind=avatar&sort=last_seen&order=desc&limit=100&offset=0";
const STICKER_URL = "GET /api/assets?kind=sticker&sort=name&order=desc&limit=100&offset=0";
// 配信者で絞った一覧。絞込はkindの次(検索語と同じ場所)に載る。
const GIFT_ALICE_URL =
  "GET /api/assets?kind=gift_icon&streamer=alice&sort=name&order=desc&limit=100&offset=0";
const EMOTE_ALICE_URL =
  "GET /api/assets?kind=emote&streamer=alice&sort=name&order=desc&limit=100&offset=0";
// 集計値で並べた一覧。
const GIFT_SENDS_URL = "GET /api/assets?kind=gift_icon&sort=sends&order=desc&limit=100&offset=0";
const EMOTE_USES_URL = "GET /api/assets?kind=emote&sort=uses&order=desc&limit=100&offset=0";
// 集計済みなのに0件の組み合わせ。「未集計」と書き分けられていることを示すのに使う。
const GIFT_BOB_URL =
  "GET /api/assets?kind=gift_icon&streamer=bob&sort=name&order=desc&limit=100&offset=0";

const GIFT_ITEMS = [
  { id: "10065", name: "Rose", sub: "gift_id 10065", bytes: 12345, mtime: 1690000000,
    content_type: "image/png", cached: true, src: "/api/assets/file?kind=gift_icon&id=10065",
    stats: [
      { key: "sends", label: "送られた個数", value: 1234, unit: "個" },
      { key: "coins", label: "コイン単価", value: 1, unit: null },
    ] },
  // 名前の源が無いgift。idしか身元が無い。送られた記録も無く、statsからその項目ごと
  // 落ちて届く ―― 0では来ない。
  { id: "77777", name: "", sub: "", bytes: 2222, mtime: 1690000001,
    content_type: "image/png", cached: true, src: "/api/assets/file?kind=gift_icon&id=77777",
    stats: [{ key: "coins", label: "コイン単価", value: 5, unit: null }] },
];

// avatarのidは sha1 40桁hex(avatar_key)。
const AVATAR_ID = "a".repeat(40);
const AVATAR_MISSING_ID = "b".repeat(40);
const AVATAR_ITEMS = [
  { id: AVATAR_ID, name: "taro", sub: "@taro", bytes: 4096, mtime: 1690000000,
    content_type: "image/jpeg", cached: true, src: `/api/assets/file?kind=avatar&id=${AVATAR_ID}` },
  // DBに人は居るが、アイコンを取り込めていない。
  { id: AVATAR_MISSING_ID, name: "hanako", sub: "@hanako", bytes: 0, mtime: 0,
    content_type: "", cached: false, src: "" },
];

const TICKET = {
  ticket: "tkt-1", kind: "gift_icon", count: 2, bytes: 14567,
  expires_at: Math.floor(Date.now() / 1000) + 600,
};

function listBody(kind, items, total) {
  return { kind, total: total ?? items.length, limit: 100, offset: 0, items };
}

function jsonError(status, detail) {
  return new Response(JSON.stringify({ detail }), {
    status, headers: { "Content-Type": "application/json" },
  });
}

const DEFAULT_ROUTES = {
  "GET /api/assets/summary": SUMMARY,
  [GIFT_URL]: listBody("gift_icon", GIFT_ITEMS),
  [AVATAR_URL]: listBody("avatar", AVATAR_ITEMS),
  [RAW_URL]: listBody("raw", []),
  [EMOTE_URL]: listBody("emote", []),
  // 語なしでも先頭100件は返る。画面はtotalを見て、並べる代わりに絞込を促す。
  [AVATAR_BROWSE_URL]: listBody("avatar", AVATAR_ITEMS, 193359),
  [STICKER_URL]: listBody("sticker", []),
  [GIFT_ALICE_URL]: listBody("gift_icon", GIFT_ITEMS),
  [EMOTE_ALICE_URL]: listBody("emote", []),
  [GIFT_SENDS_URL]: listBody("gift_icon", GIFT_ITEMS),
  [EMOTE_USES_URL]: listBody("emote", []),
  [GIFT_BOB_URL]: listBody("gift_icon", []),
};

// instanceを跨いで生き残るstorage。jsdomはJSDOM instanceごとに別のlocalStorageを持つので、
// 「画面を閉じて開き直した」再現にはこれを差し込む必要がある(pages.prefs.test.jsと同じ手)。
function sharedStorage() {
  const map = new Map();
  const store = {
    getItem: (k) => (map.has(String(k)) ? map.get(String(k)) : null),
    setItem: (k, v) => map.set(String(k), String(v)),
    removeItem: (k) => map.delete(String(k)),
    clear: () => map.clear(),
    key: (i) => Array.from(map.keys())[i] ?? null,
  };
  Object.defineProperty(store, "length", { get: () => map.size });
  return store;
}

function installStorage(store) {
  return (win) => {
    Object.defineProperty(win, "localStorage", { configurable: true, value: store });
  };
}

describe("素材画面", () => {
  let page;
  let doc;
  let errorSpy;

  async function open(routes, before) {
    page = loadPage({
      page: "assets",
      url: "http://localhost:8520/assets",
      routes: routes ?? DEFAULT_ROUTES,
      before,
    });
    doc = page.document;
    errorSpy = vi.spyOn(page.win.console, "error").mockImplementation(() => {});
    await page.settle();
    return page;
  }

  async function reopen(routes, before) {
    errorSpy.mockRestore();
    await page.close();
    await open(routes, before);
  }

  beforeEach(async () => {
    await open();
  });
  afterEach(async () => {
    errorSpy.mockRestore();
    await page.close();
  });

  const tiles = () => [...doc.querySelectorAll("#as-grid .as-tile")];
  const tileOf = (id) => tiles().find((el) => el.dataset.id === id);
  const kindButtons = () => [...doc.querySelectorAll("#as-kinds .as-kind")];
  const kindButton = (kind) => kindButtons().find((b) => b.dataset.kind === kind);
  const selectedIds = () => page.run("[...assetSelected]");
  const assetKindInfoOf = (kind) => page.run(`assetKindInfo(${JSON.stringify(kind)})`);
  const streamerField = () => doc.getElementById("as-streamer-field");
  const streamerSelect = () => doc.getElementById("as-streamer");
  const sortOptions = () => [...doc.getElementById("as-sort").options];
  const statsOf = (id) => [...tileOf(id).querySelectorAll(".as-stat")]
    .map((el) => [el.querySelector(".k").textContent, el.querySelector(".v").textContent]);
  const requested = (from) => page.calls.fetches.slice(from).map((f) => f.url);
  const emptyEl = () => doc.getElementById("as-empty");
  const noteEl = () => doc.getElementById("as-note");
  const confirmText = () => doc.querySelector(".confirm-text").textContent;
  const toastText = () => [...doc.querySelectorAll(".toast")].map((t) => t.textContent).join("\n");
  const posts = (path) =>
    page.calls.fetches.filter((f) => f.method === "POST" && f.url === path);

  async function clickConfirm() {
    const buttons = [...doc.querySelectorAll(".confirm-actions button")];
    buttons[buttons.length - 1].click();
    await page.settle();
  }

  // controlを操作する。実際のbrowserと同じくchangeを出す(bindPrefが購読している)。
  async function pick(id, value) {
    const el = doc.getElementById(id);
    el.value = value;
    expect(el.value, `#${id} に ${value} という選択肢が無い`).toBe(value);
    el.dispatchEvent(new page.win.Event("change", { bubbles: true }));
    await page.settle();
  }

  // 種別を選び直す。検索前提の種別は語を入れてから取り直す(debounceは介さない)。
  async function switchKind(kind, query) {
    kindButton(kind).click();
    await page.settle();
    if (query !== undefined) {
      doc.getElementById("as-q").value = query;
      page.run("loadItems(true)");
      await page.settle();
    }
  }

  describe("種別pane", () => {
    it("種別の並びと件数はserverの応答から作る", () => {
      expect(kindButtons().map((b) => b.dataset.kind))
        .toEqual(["gift_icon", "emote", "avatar", "sticker", "raw"]);
      expect(kindButtons().map((b) => b.querySelector(".as-kind-name").textContent))
        .toEqual(["Giftアイコン", "Emote", "Userアイコン", "スタンプ", "その他"]);
      expect(kindButton("gift_icon").querySelector(".as-kind-meta").textContent).toContain("3件");
    });

    // 画面が種別を知っていないことの証明。応答にしか無い種別が、そのまま棚に並ぶ。
    it("応答に知らない種別が増えても、そのまま棚に並ぶ", async () => {
      const kinds = [{ kind: "banner", label: "バナー", count: 7, bytes: 1024, scanned_at: 1,
                       duration_ms: 1, sorts: ["name"] }];
      await reopen({
        "GET /api/assets/summary": { pool_root: "K:\\recordings", kinds },
        "GET /api/assets?kind=banner&sort=name&order=desc&limit=100&offset=0":
          listBody("banner", []),
      });
      expect(kindButtons().map((b) => b.dataset.kind)).toEqual(["banner"]);
      expect(doc.getElementById("as-title").textContent).toBe("バナー");
    });

    it("並び順の選択肢も種別ごとに応答から作る", async () => {
      const options = () => sortOptions().map((o) => o.value);
      expect(options()).toEqual(["name", "size", "mtime", "sends", "coins"]);
      await switchKind("avatar");
      expect(options()).toEqual(["last_seen", "name", "freq"]);
      // 先頭がその種別の既定。
      expect(doc.getElementById("as-sort").value).toBe("last_seen");
    });

    it("並び順をserverが出していない種別ではcontrolを出さず、requestにも載せない", async () => {
      await switchKind("raw");
      expect(doc.getElementById("as-sort-field").className).toContain("hidden");
      expect(doc.getElementById("as-order-field").className).toContain("hidden");
      expect(page.calls.fetches.some((f) => f.url === "/api/assets?kind=raw&limit=100&offset=0"))
        .toBe(true);
    });

    // 判定の根拠は一覧応答のtotal。summaryのcountを根拠にすると、未集計(count:null)の
    // 種別だけ判定できず、その一覧requestでしか埋まらないsnapshotが永久に埋まらない。
    it("件数の多い種別はrequestを出したうえで、応答のtotalを根拠に絞込を促す", async () => {
      const before = page.calls.fetches.length;
      await switchKind("avatar");
      expect(page.calls.fetches.slice(before).map((f) => f.url))
        .toContain("/api/assets?kind=avatar&sort=last_seen&order=desc&limit=100&offset=0");
      // 先頭ぶんは出す(既定の並びはserverが決めた意味を持つ。avatarならlast_seen=最近見た順)。
      expect(tiles().map((el) => el.dataset.id)).toEqual([AVATAR_ID, AVATAR_MISSING_ID]);
      // 案内は一覧の上。先頭ぶんの下だと、scrollし切った人にしか届かない。
      expect(noteEl().textContent).toContain("193,359件");
      expect(noteEl().textContent).toContain("先頭 2件");
      expect(noteEl().compareDocumentPosition(doc.getElementById("as-grid")))
        .toBe(doc.DOCUMENT_POSITION_FOLLOWING);
      // 続きは読ませない(無限scrollにしない)。
      expect(doc.getElementById("as-more").className).toContain("hidden");
      // 「0件」でも取得失敗でもない。
      expect(emptyEl().className).not.toContain("list-failed");
    });

    // 案内の根拠はcountではなくtotal。countがnullの種別でも判定が効くこと。
    it("集計していない種別でも、totalが閾値を超えれば案内を出す", async () => {
      await reopen({
        ...DEFAULT_ROUTES,
        [STICKER_URL]: listBody("sticker", [
          { id: "s1", name: "やった", sub: "", bytes: 512, mtime: 1690000000, cached: true },
        ], 90000),
      });
      await switchKind("sticker");
      expect(assetKindInfoOf("sticker").count).toBeNull();
      expect(noteEl().textContent).toContain("90,000件");
      expect(noteEl().textContent).toContain("先頭 1件");
    });

    it("小さい種別は語が無くてもそのまま並べ、案内も出さない", () => {
      expect(tiles().map((el) => el.dataset.id)).toEqual(["10065", "77777"]);
      expect(emptyEl().className).toContain("hidden");
      expect(noteEl().textContent).toBe("");
    });

    it("語を入れれば案内は消え、普通の一覧に戻る", async () => {
      await switchKind("avatar", "taro");
      expect(tiles()).toHaveLength(2);
      expect(noteEl().textContent).toBe("");
    });
  });

  describe("まだ集計していない種別(count:null)", () => {
    it("棚では「未集計」と名乗る(0件と書かない)", () => {
      const meta = kindButton("sticker").querySelector(".as-kind-meta").textContent;
      expect(meta).toBe("未集計");
      expect(meta).not.toContain("0件");
    });

    // 集計していない種別で一覧requestを止めると、その一覧requestでしかsnapshotが埋まらない
    // 種別は永久に「未集計」のままになり、264件の棚すら開けなくなる(deadlock)。
    it("集計していなくても一覧requestは出す", async () => {
      const before = page.calls.fetches.length;
      await switchKind("sticker");
      expect(page.calls.fetches.slice(before).map((f) => f.url))
        .toContain("/api/assets?kind=sticker&sort=name&order=desc&limit=100&offset=0");
    });

    it("集計していない種別でも中身が並ぶ", async () => {
      await reopen({
        ...DEFAULT_ROUTES,
        [STICKER_URL]: listBody("sticker", [
          { id: "s1", name: "やった", sub: "", bytes: 512, mtime: 1690000000, cached: true },
        ]),
      });
      await switchKind("sticker");
      expect(tiles().map((el) => el.dataset.id)).toEqual(["s1"]);
    });

    // 一覧requestがdirを走査したついでにsnapshotが埋まる。棚だけ「未集計」のまま残ると、
    // 一覧に中身が出ているのに数字が無い、という食い違いになる。
    it("一覧を開いた後は集計を読み直し、棚の数字を追いつかせる", async () => {
      const counted = {
        ...SUMMARY,
        kinds: SUMMARY.kinds.map((k) => (k.kind === "sticker"
          ? { ...k, count: 1, bytes: 512, listable: 1, scanned_at: 1690000500, duration_ms: 5 } : k)),
      };
      let summaryCalls = 0;
      await reopen({
        ...DEFAULT_ROUTES,
        "GET /api/assets/summary": () => {
          summaryCalls += 1;
          return summaryCalls === 1 ? SUMMARY : counted;
        },
        [STICKER_URL]: listBody("sticker", [
          { id: "s1", name: "やった", sub: "", bytes: 512, mtime: 1690000000, cached: true },
        ]),
      });
      expect(kindButton("sticker").querySelector(".as-kind-meta").textContent).toBe("未集計");
      await switchKind("sticker");
      expect(summaryCalls).toBe(2);
      expect(kindButton("sticker").querySelector(".as-kind-meta").textContent).toContain("1件");
    });

    // 本当に0件の種別とは書き分ける。どちらも「並んでいない」が、理由が違う。
    it("集計済みで0件の種別は「未集計」と言わない", async () => {
      expect(kindButton("raw").querySelector(".as-kind-meta").textContent).toContain("0件");
      await switchKind("raw");
      expect(emptyEl().textContent).toBe("素材なし");
    });

    it("再集計するとその種別だけを数え直し、結末を名乗る", async () => {
      await switchKind("sticker");
      const counted = {
        ...SUMMARY,
        kinds: SUMMARY.kinds.map((k) => (k.kind === "sticker"
          ? { ...k, count: 4, bytes: 2048, scanned_at: 1690000500, duration_ms: 25 } : k)),
      };
      page.win.fetch = ((original) => (input, init) => {
        const url = String(typeof input === "string" ? input : input.url);
        if (url === "/api/assets/rescan") {
          page.calls.fetches.push({ url, method: "POST", body: init && init.body });
          return Promise.resolve(new Response(JSON.stringify(counted), {
            status: 200, headers: { "Content-Type": "application/json" },
          }));
        }
        return original(input, init);
      })(page.win.fetch);

      doc.getElementById("as-rescan").click();
      await page.settle();
      expect(JSON.parse(posts("/api/assets/rescan")[0].body)).toEqual({ kind: "sticker" });
      expect(kindButton("sticker").querySelector(".as-kind-meta").textContent).toContain("4件");
      expect(toastText()).toContain("4件");
    });
  });

  // diskに在る数(count)と、一覧に出せる数(listable)が食い違う種別がある。黙ると、
  // 2つの数字が違う理由も、ZIPの件数が一覧より多い理由も画面から読めない。
  describe("一覧に出せない素材があるとき", () => {
    it("差を注記として名乗り、全件ZIPには入ることまで書く", async () => {
      await switchKind("avatar");
      const summary = doc.getElementById("as-summary").textContent;
      expect(summary).toContain("234,480件");
      expect(summary).toContain("一覧に出せる 193,359件");
      expect(summary).toContain("41,121件");
      expect(summary).toContain("全件ZIPには入ります");
    });

    it("食い違いの無い種別では注記を出さない", () => {
      expect(doc.getElementById("as-summary").textContent).not.toContain("一覧に出せる");
    });

    it("listableを持たない応答でも壊れず、注記も出さない", async () => {
      await switchKind("emote");
      expect(page.errors.map(String)).toEqual([]);
      expect(doc.getElementById("as-summary").textContent).not.toContain("一覧に出せる");
    });

    it("未集計の種別では注記を出さない(引き算する数が無い)", async () => {
      await switchKind("sticker");
      expect(doc.getElementById("as-summary").textContent).toContain("未集計");
      expect(doc.getElementById("as-summary").textContent).not.toContain("一覧に出せる");
    });
  });

  describe("集計の新しさ", () => {
    it("件数には集計時点を添える(今の数と読ませない)", () => {
      const summary = doc.getElementById("as-summary").textContent;
      expect(summary).toContain("集計時点");
      expect(summary).toContain("3件");
    });

    it("画面を開いただけでは走査を求めない(refreshを渡さない)", () => {
      const calls = page.calls.fetches.filter((f) => f.url.startsWith("/api/assets/summary"));
      expect(calls).toHaveLength(1);
      expect(calls[0].url).toBe("/api/assets/summary");
    });
  });

  // 配信者で絞れるかどうかは種別ごとに違い、それを名乗るのはserver(kindのfilters)。
  // 種別名で出し分けると、同じ絞込を受ける種別が増えた時にその種別だけ黙って絞れない。
  describe("配信者で絞る", () => {
    it("filtersにstreamerを持つ種別でだけcontrolを出す", async () => {
      expect(streamerField().className).not.toContain("hidden");
      await switchKind("sticker");
      expect(streamerField().className).toContain("hidden");
    });

    // 画面が種別を知っていないことの証明。種別名ではなくfiltersだけが出し分けを決める。
    it("画面が知らない種別でも、filtersが名乗れば出す", async () => {
      await reopen({
        "GET /api/assets/summary": {
          pool_root: "K:\\recordings",
          streamers: SUMMARY.streamers,
          kinds: [{ kind: "banner", label: "バナー", count: 7, bytes: 1024, scanned_at: 1,
            duration_ms: 1, filters: ["streamer"], sorts: ["name"] }],
        },
        "GET /api/assets?kind=banner&sort=name&order=desc&limit=100&offset=0":
          listBody("banner", []),
      });
      expect(streamerField().className).not.toContain("hidden");
    });

    it("選択肢はsummaryのstreamersから作り、未選択(すべて)も選べる", () => {
      expect([...streamerSelect().options].map((o) => [o.value, o.textContent]))
        .toEqual([["", "すべて"], ["alice", "alice"], ["bob", "ぼぶ"]]);
      expect(streamerSelect().value).toBe("");
    });

    it("選べる配信者が居なければcontrolごと出さない", async () => {
      await reopen({ ...DEFAULT_ROUTES,
        "GET /api/assets/summary": { ...SUMMARY, streamers: [] } });
      expect(streamerField().className).toContain("hidden");
    });

    it("streamersを持たない応答でも壊れず、controlも出さない", async () => {
      await reopen({ ...DEFAULT_ROUTES,
        "GET /api/assets/summary": { pool_root: SUMMARY.pool_root, kinds: SUMMARY.kinds } });
      expect(page.errors.map(String)).toEqual([]);
      expect(streamerField().className).toContain("hidden");
      expect(tiles().map((el) => el.dataset.id)).toEqual(["10065", "77777"]);
    });

    it("配信者を選ぶとstreamerがrequestに載る", async () => {
      const before = page.calls.fetches.length;
      await pick("as-streamer", "alice");
      expect(requested(before)).toContain(
        "/api/assets?kind=gift_icon&streamer=alice&sort=name&order=desc&limit=100&offset=0");
    });

    it("「すべて」へ戻すとstreamerを載せない", async () => {
      await pick("as-streamer", "alice");
      const before = page.calls.fetches.length;
      await pick("as-streamer", "");
      expect(requested(before)).toContain(GIFT_URL.replace("GET ", ""));
      expect(requested(before).some((u) => u.includes("streamer="))).toBe(false);
    });

    // 400を踏むより先に、渡せない組み合わせを画面が作らない。
    it("絞込を受けない種別へ移ったらstreamerを渡さない", async () => {
      await pick("as-streamer", "alice");
      const before = page.calls.fetches.length;
      await switchKind("sticker");
      expect(requested(before))
        .toContain("/api/assets?kind=sticker&sort=name&order=desc&limit=100&offset=0");
      expect(requested(before).some((u) => u.includes("streamer="))).toBe(false);
    });

    // 配信者は種別に属さない身元なので、種別を移っても引き継ぐ(選択=idとは違う)。
    it("受ける種別へ移った時は選んだ配信者を引き継ぐ", async () => {
      await pick("as-streamer", "alice");
      const before = page.calls.fetches.length;
      await switchKind("emote");
      expect(streamerSelect().value).toBe("alice");
      expect(requested(before)).toContain(
        "/api/assets?kind=emote&streamer=alice&sort=name&order=desc&limit=100&offset=0");
    });

    // 検索語と同じ性質の絞込なので、選択(assetSelected)は捨てない。
    it("配信者を変えても選択は捨てない", async () => {
      doc.getElementById("as-select-all").click();
      expect(selectedIds()).toHaveLength(2);
      await pick("as-streamer", "alice");
      expect(selectedIds()).toHaveLength(2);
    });

    // 先回りしてなお400が来たら、断った理由はserverの文言をそのまま出す。
    it("400が返ったらserverの文言をそのまま名乗る", async () => {
      await reopen({ ...DEFAULT_ROUTES,
        [GIFT_ALICE_URL]: jsonError(400, "この種別は配信者で絞り込めません。") });
      await pick("as-streamer", "alice");
      expect(toastText()).toContain("この種別は配信者で絞り込めません。");
      // 0件としては描かない。
      expect(emptyEl().className).toContain("list-failed");
    });
  });

  // 配信者の絞込は「繰り返し同じ値を選ぶcontrol」なので次の訪問へ残す(検索語は残さない)。
  describe("配信者の絞込を次に開いた時も残す", () => {
    it("選んだ配信者で始まる", async () => {
      const store = sharedStorage();
      await reopen(DEFAULT_ROUTES, installStorage(store));
      await pick("as-streamer", "alice");
      expect(store.getItem("tictok.assets.streamer")).toBe("alice");

      await reopen(DEFAULT_ROUTES, installStorage(store));
      expect(streamerSelect().value).toBe("alice");
      expect(page.calls.fetches.map((f) => f.url)).toContain(
        "/api/assets?kind=gift_icon&streamer=alice&sort=name&order=desc&limit=100&offset=0");
    });

    // 監視を外した配信者を指したままにすると、一致0件の一覧から戻れなくなる。
    it("保存値が候補に無ければ「すべて」で始まる", async () => {
      const store = sharedStorage();
      store.setItem("tictok.assets.streamer", "監視を外した人");
      await reopen(DEFAULT_ROUTES, installStorage(store));
      expect(streamerSelect().value).toBe("");
      expect(page.calls.fetches.some((f) => f.url.includes("streamer="))).toBe(false);
    });
  });

  // 何の項目が来るか・その語・記録が無い時に落とすかは、すべてserverが決める。
  describe("集計値(stats)", () => {
    it("来た配列をそのまま描く(labelはserverの語、桁は区切る)", () => {
      expect(statsOf("10065")).toEqual([["送られた個数", "1,234個"], ["コイン単価", "1"]]);
    });

    // 「送られた記録が無い」と「0回送られた」は別。落ちている項目を0で補わない。
    it("落ちている項目は0として描かない", () => {
      expect(statsOf("77777")).toEqual([["コイン単価", "5"]]);
      expect(tileOf("77777").textContent).not.toContain("送られた個数");
    });

    it("statsを持たないitemでも壊れない", async () => {
      await switchKind("avatar", "taro");
      expect(page.errors.map(String)).toEqual([]);
      expect(tiles().map((el) => el.dataset.id)).toEqual([AVATAR_ID, AVATAR_MISSING_ID]);
      expect(tileOf(AVATAR_ID).querySelectorAll(".as-stat")).toHaveLength(0);
    });

    it("値の無い項目は描かない", async () => {
      await reopen({ ...DEFAULT_ROUTES,
        [GIFT_URL]: listBody("gift_icon", [{ ...GIFT_ITEMS[0],
          stats: [{ key: "sends", label: "送られた個数", value: null, unit: "個" }] }]) });
      expect(statsOf("10065")).toEqual([]);
    });

    // 並び順の識別子とstatsのkeyが同じ物なので、画面は対応表を持たずに指せる。
    it("並びの基準になっている数字を強調する", async () => {
      // 既定(名前)では数字で並んでいないので、どれも強調しない。
      expect(tileOf("10065").querySelectorAll(".as-stat.is-sorted")).toHaveLength(0);
      await pick("as-sort", "sends");
      expect([...tileOf("10065").querySelectorAll(".as-stat.is-sorted")]
        .map((el) => el.querySelector(".k").textContent)).toEqual(["送られた個数"]);
      // 「今この数字で並んでいる」ことは is-sorted の見た目が名乗る。hoverには書かない
      // (見れば分かる物をtooltipへ二重に置かない)。
      expect(tileOf("10065").querySelector(".as-stat.is-sorted").title)
        .toBe("送られた個数: 1,234個");
    });
  });

  describe("並び順のlabel", () => {
    it("集計値の並び順も日本語で出す", () => {
      expect(sortOptions().map((o) => o.textContent))
        .toEqual(["名前", "容量", "更新日時", "送られた個数", "コイン単価"]);
    });

    // 訳語を勝手に作ると、serverが受ける値と画面の語がずれる。keyのまま出す。
    it("画面が知らないkeyは訳さずそのまま出す", async () => {
      await reopen({
        "GET /api/assets/summary": { ...SUMMARY,
          kinds: [{ kind: "gift_icon", label: "Giftアイコン", count: 1, bytes: 1, listable: 1,
            scanned_at: 1, duration_ms: 1, filters: [], sorts: ["mystery_metric"] }] },
        "GET /api/assets?kind=gift_icon&sort=mystery_metric&order=desc&limit=100&offset=0":
          listBody("gift_icon", []),
      });
      expect(sortOptions().map((o) => o.textContent)).toEqual(["mystery_metric"]);
    });
  });

  describe("名前を持たない素材", () => {
    it("idだけで名乗り、代わりの名前を作らない", () => {
      const tile = tileOf("77777");
      expect(tile.querySelector(".as-name").textContent).toBe("77777");
      expect(tile.querySelector(".as-sub").textContent).toBe("");
    });

    it("名前がある素材はその名前を出す", () => {
      const tile = tileOf("10065");
      expect(tile.querySelector(".as-name").textContent).toBe("Rose");
      expect(tile.querySelector(".as-sub").textContent).toBe("gift_id 10065");
    });
  });

  describe("cacheが無い素材(cached:false)", () => {
    it("0件として畳まず「未取得」として並べる", async () => {
      await switchKind("avatar", "taro");
      expect(tiles().map((el) => el.dataset.id)).toEqual([AVATAR_ID, AVATAR_MISSING_ID]);
      const missing = tileOf(AVATAR_MISSING_ID);
      expect(missing.className).toContain("as-missing");
      expect(missing.textContent).toContain("未取得");
    });

    it("選択もDownloadもできない", async () => {
      await switchKind("avatar", "taro");
      const missing = tileOf(AVATAR_MISSING_ID);
      expect(missing.querySelector(".as-pick").disabled).toBe(true);
      expect(missing.querySelector(".as-dl")).toBeNull();
      missing.click();
      expect(selectedIds()).toEqual([]);
    });

    it("「表示中をすべて選択」でも拾わない", async () => {
      await switchKind("avatar", "taro");
      doc.getElementById("as-select-all").click();
      expect(selectedIds()).toEqual([AVATAR_ID]);
    });

    it("cacheが在る素材は選択もDownloadもできる", async () => {
      await switchKind("avatar", "taro");
      const ok = tileOf(AVATAR_ID);
      expect(ok.querySelector(".as-dl").getAttribute("href"))
        .toBe(`/api/assets/file?kind=avatar&id=${AVATAR_ID}&download=1`);
      ok.click();
      expect(selectedIds()).toEqual([AVATAR_ID]);
      expect(doc.getElementById("as-zip-selected").disabled).toBe(false);
      expect(doc.getElementById("as-zip-selected").textContent).toContain("1件");
    });
  });

  describe("ZIP(発券→確認→受け取り)", () => {
    function withTicket(ticket) {
      page.win.fetch = ((original) => (input, init) => {
        const url = String(typeof input === "string" ? input : input.url);
        const method = ((init && init.method) || "GET").toUpperCase();
        if (method === "POST" && url === "/api/assets/archive") {
          page.calls.fetches.push({ url, method, body: init && init.body });
          return Promise.resolve(ticket instanceof Response
            ? ticket
            : new Response(JSON.stringify(ticket), {
              status: 200, headers: { "Content-Type": "application/json" },
            }));
        }
        return original(input, init);
      })(page.win.fetch);
    }

    it("選択をZIPは発券し、serverが数えた件数と容量を確認に出す", async () => {
      withTicket(TICKET);
      doc.getElementById("as-select-all").click();
      doc.getElementById("as-zip-selected").click();
      await page.settle();
      expect(JSON.parse(posts("/api/assets/archive")[0].body))
        .toEqual({ kind: "gift_icon", ids: ["10065", "77777"] });
      // 画面が手元の行を足した値ではなく、券が名乗った値。
      expect(confirmText()).toContain("2件");
      expect(confirmText()).toContain("14.2 KB");
    });

    it("確認したら券のURLを引く(idsをURLへ並べない)", async () => {
      withTicket(TICKET);
      doc.getElementById("as-select-all").click();
      doc.getElementById("as-zip-selected").click();
      await page.settle();
      await clickConfirm();
      expect(doc.getElementById("as-dl-frame").getAttribute("src"))
        .toBe("/api/assets/archive/tkt-1");
    });

    it("取り消したら受け取りに行かない", async () => {
      withTicket(TICKET);
      doc.getElementById("as-select-all").click();
      doc.getElementById("as-zip-selected").click();
      await page.settle();
      doc.querySelectorAll(".confirm-actions button")[0].click();
      await page.settle();
      expect(doc.getElementById("as-dl-frame").getAttribute("src")).toBeNull();
    });

    it("全件ZIPはidsを渡さず、検索中はその旨を確認に出す", async () => {
      withTicket({ ...TICKET, count: 3, bytes: 27800000 });
      doc.getElementById("as-q").value = "rose";
      doc.getElementById("as-zip-all").click();
      await page.settle();
      expect(JSON.parse(posts("/api/assets/archive")[0].body)).toEqual({ kind: "gift_icon" });
      expect(confirmText()).toContain("検索での絞込は反映されません");
    });

    // 効いている絞込だけを名指しする。使っていない絞込まで並べると、何が反映されないのかが
    // ぼやける。
    it("配信者で絞っている時はそれも反映されないことを名乗る", async () => {
      await pick("as-streamer", "alice");
      withTicket({ ...TICKET, count: 3, bytes: 27800000 });
      doc.getElementById("as-zip-all").click();
      await page.settle();
      expect(confirmText()).toContain("配信者での絞込は反映されません");
      expect(confirmText()).not.toContain("検索");
    });

    // 上限はserverのsettingsが持つ。画面が件数で先回りして断ると、上限を変えた時に
    // 画面だけが古い数で断り続ける。
    it("件数の上限を画面が持たない(何件選んでも発券まで行く)", async () => {
      withTicket(jsonError(400, "一度に指定できるのは1000件までです。"));
      // 400件を選んだ状態を直接作る(一覧を400件描く必要はない)。buttonの押せる/押せないは
      // 選択の件数が決めるので、描き直しまで済ませてから押す。
      page.run(`assetSelected.clear();`
        + `for (let i = 0; i < 400; i++) assetSelected.add("c".repeat(39) + i);`
        + `renderSelection();`);
      doc.getElementById("as-zip-selected").click();
      await page.settle();
      const body = JSON.parse(posts("/api/assets/archive")[0].body);
      expect(body.ids).toHaveLength(400);
      // 断りはserverの文言をそのまま出す。
      expect(toastText()).toContain("一度に指定できるのは1000件までです。");
      expect(doc.querySelector(".confirm-text")).toBeNull();
    });

    it("期限の切れた券は引きに行かず、切れたことを名乗る", async () => {
      withTicket({ ...TICKET, expires_at: Math.floor(Date.now() / 1000) - 1 });
      doc.getElementById("as-select-all").click();
      doc.getElementById("as-zip-selected").click();
      await page.settle();
      await clickConfirm();
      expect(doc.getElementById("as-dl-frame").getAttribute("src")).toBeNull();
      expect(toastText()).toContain("有効期限が切れました");
    });

    it("入れる素材が無い券は受け取りに行かない", async () => {
      withTicket({ ...TICKET, count: 0, bytes: 0 });
      doc.getElementById("as-select-all").click();
      doc.getElementById("as-zip-selected").click();
      await page.settle();
      expect(doc.querySelector(".confirm-text")).toBeNull();
      expect(toastText()).toContain("ZIPに入れられる素材がありませんでした");
    });
  });

  describe("選択", () => {
    it("種別を移ると選択は捨てる(別の棚の物が混ざったZIPになる)", async () => {
      doc.getElementById("as-select-all").click();
      expect(selectedIds()).toHaveLength(2);
      await switchKind("emote");
      expect(selectedIds()).toEqual([]);
    });

    it("選択が無い間はZIPのbuttonを押せない", () => {
      expect(doc.getElementById("as-zip-selected").disabled).toBe(true);
      expect(doc.getElementById("as-clear").disabled).toBe(true);
    });
  });

  describe("取得に失敗したとき", () => {
    it("0件ではなく取得失敗として名乗る", async () => {
      // 一覧だけstub不在 = 404。
      await reopen({ "GET /api/assets/summary": SUMMARY });
      expect(emptyEl().className).toContain("list-failed");
      expect(emptyEl().textContent).toContain("取得できませんでした");
      expect(tiles()).toHaveLength(0);
    });
  });
  describe("集計していない種別で絞り込んだとき", () => {
    // 集計(rescan)が無いと配信者の絞込も集計順も必ず0件になる。それを「素材なし」
    // と出すと、集計すれば出てくる物を無いことにする。
    it("配信者で絞ると0件ではなく未集計として名乗る", async () => {
      await switchKind("emote");
      await pick("as-streamer", "alice");
      expect(emptyEl().textContent).toContain("まだ集計していません");
      expect(emptyEl().textContent).toContain("0件ではありません");
      expect(emptyEl().textContent).toContain("再集計");
      expect(emptyEl().textContent).not.toContain("素材なし");
    });

    it("集計順に切り替えたときも未集計として名乗る", async () => {
      await switchKind("emote");
      await pick("as-streamer", "");
      await pick("as-sort", "uses");
      expect(emptyEl().textContent).toContain("まだ集計していません");
    });

    it("集計の要らない並び(名前)で0件なら、素材が無いと名乗る", async () => {
      await switchKind("emote");
      await pick("as-streamer", "");
      await pick("as-sort", "name");
      expect(emptyEl().textContent).toContain("素材なし");
    });

    it("集計済みの種別では0件を素材が無いと名乗る", async () => {
      await pick("as-streamer", "bob");
      expect(tiles()).toHaveLength(0);
      expect(emptyEl().textContent).toContain("素材なし");
      expect(emptyEl().textContent).not.toContain("まだ集計していません");
    });

    it("aggregatedを持たない応答では未集計扱いにしない(古いserverでも壊れない)", async () => {
      const kinds = SUMMARY.kinds.map((k) => {
        const copy = { ...k };
        delete copy.aggregated;
        return copy;
      });
      await reopen({ ...DEFAULT_ROUTES,
        "GET /api/assets/summary": { ...SUMMARY, kinds } });
      await switchKind("emote");
      await pick("as-streamer", "alice");
      expect(emptyEl().textContent).not.toContain("まだ集計していません");
    });
  });
});
