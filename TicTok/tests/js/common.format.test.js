import { describe, it, expect, beforeAll, afterAll, vi } from "vitest";
import { loadCommon } from "./helpers/page.js";

// 画面に出る数値・時刻・録画名の書式。ここが崩れると全画面が同時に崩れるが、
// 見た目の崩れは「なんとなく変」で済まされて気付かれにくい。
describe("common.js の書式helper", () => {
  let win;
  let page;
  beforeAll(() => {
    page = loadCommon();
    win = page.win;
  });
  afterAll(async () => page.close());

  describe("fmtNum / fmtCompact", () => {
    it("3桁区切りを入れる", () => {
      expect(win.fmtNum(1234567)).toBe("1,234,567");
      expect(win.fmtNum(0)).toBe("0");
    });

    it("null・undefined・空文字は0として扱う", () => {
      expect(win.fmtNum(null)).toBe("0");
      expect(win.fmtNum(undefined)).toBe("0");
      expect(win.fmtNum("")).toBe("0");
    });

    it("fmtCompactは千・百万で丸め、.0は落とす", () => {
      expect(win.fmtCompact(999)).toBe("999");
      expect(win.fmtCompact(1500)).toBe("1.5k");
      expect(win.fmtCompact(2000)).toBe("2k");
      expect(win.fmtCompact(1_500_000)).toBe("1.5M");
      expect(win.fmtCompact(-2500)).toBe("-2.5k");
    });
  });

  describe("fmtDuration", () => {
    it("HH:MM:SS へ0埋めする", () => {
      expect(win.fmtDuration(0)).toBe("00:00:00");
      expect(win.fmtDuration(3661)).toBe("01:01:01");
      expect(win.fmtDuration(59.9)).toBe("00:00:59");
    });

    it("24時間を超えても時間を繰り上げない(日へ持ち上げない)", () => {
      expect(win.fmtDuration(90000)).toBe("25:00:00");
    });
  });

  describe("日時", () => {
    // 2026-07-21 14:49:49 JST
    const EPOCH = Date.UTC(2026, 6, 21, 5, 49, 49) / 1000;

    it("fmtTimeは24時制の時刻", () => {
      expect(win.fmtTime(EPOCH)).toBe("14:49:49");
    });

    it("fmtYmdは YYYYMMDD", () => {
      expect(win.fmtYmd(EPOCH)).toBe("20260721");
    });

    it("未取得(0/null)は日時を捏造せず — を出す", () => {
      expect(win.fmtDateTime(0)).toBe("-");
      expect(win.fmtDateTime(null)).toBe("-");
      expect(win.fmtYmd(0)).toBe("-");
    });
  });

  describe("容量", () => {
    it("fmtBytesGb は GB 単位1桁", () => {
      expect(win.fmtBytesGb(1024 ** 3)).toBe("1.0 GB");
      expect(win.fmtBytesGb(0)).toBe("0.0 GB");
    });

    it("fmtBytes は単位を跨ぐ(小さいfileが0.0GBへ潰れない)", () => {
      expect(win.fmtBytes(512)).toBe("512 B");
      expect(win.fmtBytes(1536)).toBe("1.5 KB");
      expect(win.fmtBytes(1024 ** 2 * 150)).toBe("150 MB");
      expect(win.fmtBytes(1024 ** 3 * 2.5)).toBe("2.5 GB");
    });

    it("0以下は0 Bではなく — (実体が無いことと0 byteを混ぜない)", () => {
      expect(win.fmtBytes(0)).toBe("—");
      expect(win.fmtBytes(null)).toBe("—");
    });
  });

  describe("Session番号・録画名", () => {
    it("sessionNo は5桁0埋め", () => {
      expect(win.sessionNo(339)).toBe("00339");
      expect(win.sessionNo(123456)).toBe("123456");
    });

    it("sessionNo は空を空のまま返し、数値でない値はそのまま返す", () => {
      expect(win.sessionNo(null)).toBe("");
      expect(win.sessionNo("")).toBe("");
      expect(win.sessionNo("abc")).toBe("abc");
    });

    it("recNo はfile名の先頭番号を正とする", () => {
      const rec = { filename: "00339_user_20260721_144949.mp4", session_id: 705 };
      expect(win.recStem(rec)).toBe("00339_user_20260721_144949");
      expect(win.recNo(rec)).toBe("00339");
      expect(win.recTag(rec)).toBe("#00339");
    });

    it("file名が規約から外れた録画はsession_id側へ落ちる", () => {
      const rec = { filename: "index.m3u8", session_id: 42 };
      expect(win.recNo(rec)).toBe("00042");
      expect(win.recName(rec)).toBe("#00042 index");
    });

    it("session削除済み(session_id=null)でfile名も規約外なら番号を名乗らない", () => {
      const rec = { filename: "index.m3u8", session_id: null };
      expect(win.recTag(rec)).toBe("—");
      expect(win.recName(rec)).toBe("index");
    });

    it("規約どおりのfile名はそれ自体が番号を名乗るので番号を前置しない", () => {
      const rec = { filename: "00339_user_20260721_144949.mp4", session_id: 705 };
      expect(win.recName(rec)).toBe("00339_user_20260721_144949");
    });
  });

  describe("avatar", () => {
    it("CDN URL は同一originのproxyへ通す", () => {
      const src = win.avatarSrc("https://p16.tiktokcdn.com/x.jpeg", "someone");
      expect(src).toBe(
        "/api/avatar?u=" + encodeURIComponent("https://p16.tiktokcdn.com/x.jpeg") + "&id=someone",
      );
    });

    it("data: と proxy済みURLは素通しする(二重proxyしない)", () => {
      expect(win.avatarSrc("data:image/png;base64,AAA")).toBe("data:image/png;base64,AAA");
      expect(win.avatarSrc("/api/avatar?u=x")).toBe("/api/avatar?u=x");
      expect(win.avatarSrc("")).toBe("");
    });

    it("avatarChar は表示名の頭文字、無ければ ?", () => {
      expect(win.avatarChar({ nickname: "たろう" })).toBe("た");
      expect(win.avatarChar({ unique_id: "someone" })).toBe("S");
      expect(win.avatarChar({})).toBe("?");
      expect(win.avatarChar(null)).toBe("?");
    });
  });

  describe("movingAverage", () => {
    it("窓が埋まるまでは在るぶんだけで平均する", () => {
      expect(win.movingAverage([1, 2, 3, 4], 2)).toEqual([1, 1.5, 2.5, 3.5]);
      expect(win.movingAverage([10, 20, 30], 5)).toEqual([10, 15, 20]);
    });

    it("空配列は空配列", () => {
      expect(win.movingAverage([], 3)).toEqual([]);
    });
  });

  describe("decorateMarkers", () => {
    it("battleだけは通し番号を振り、他はkind固有のtagを付ける", () => {
      const out = win.decorateMarkers([
        { time: 1, kind: "record" },
        { time: 2, kind: "battle" },
        { time: 3, kind: "battle" },
        { time: 4, kind: "live_end" },
      ]);
      expect(out.map((m) => m.tag)).toEqual(["REC", "PK1", "PK2", "終了"]);
    });

    it("未知のkindでも落とさず既定tagを当てる", () => {
      const out = win.decorateMarkers([{ time: 1, kind: "なにか未知" }]);
      expect(out[0].tag).toBe("•");
      expect(out[0].color).toBeTruthy();
    });

    it("null は空配列", () => {
      expect(win.decorateMarkers(null)).toEqual([]);
    });
  });
});

// server の error detail は日本語(app自身の説明)と英語(FastAPI既定・Python例外)が混ざる。
// 英語をそのまま画面へ出さない置き換えが効いているかを見る。
describe("common.js のHTTP error文言", () => {
  let win;
  let page;
  let warn;
  beforeAll(() => {
    page = loadCommon();
    win = page.win;
    warn = vi.spyOn(win.console, "warn").mockImplementation(() => {});
  });
  afterAll(async () => {
    warn.mockRestore();
    await page.close();
  });

  it("英語のdetailはstatusから引いた日本語へ置き換え、生文言はdetailへ残す", () => {
    const err = win.httpError(404, "Not Found");
    expect(err.message).toBe("対象が見つかりませんでした（Serverのcodeが古い可能性があります）。");
    expect(err.status).toBe(404);
    expect(err.detail).toBe("Not Found");
    expect(warn).toHaveBeenCalled();
  });

  it("日本語のdetailはapp自身の説明なのでそのまま出す", () => {
    const err = win.httpError(409, "録画中のため実行できません。");
    expect(err.message).toBe("録画中のため実行できません。");
    expect(err.detail).toBe("録画中のため実行できません。");
  });

  it("表に無いstatusはstatusを添えた汎用文言になる", () => {
    expect(win.httpError(418, "").message).toBe("Serverが処理できませんでした（HTTP 418）。");
  });

  it("errorDetailText は status と生文言を繋ぐ", () => {
    expect(win.errorDetailText({ status: 404, detail: "Not Found" })).toBe("HTTP 404 / Not Found");
    expect(win.errorDetailText({ status: 0, detail: "fetch failed" })).toBe("fetch failed");
    expect(win.errorDetailText(null)).toBe("");
  });
});
