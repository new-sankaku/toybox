import { describe, it, expect, beforeEach, afterEach } from "vitest";
import { loadCommon } from "./helpers/page.js";

// ts結合(pack)で seg*.ts が pack*.ts へ束ねられると、その最中に開いていたpageは消えた
// segmentを指すplaylistを持ち続け、再生がそこへ届いた瞬間に404で止まる。listを引き直せば
// 直るので、どの失敗を「引き直せば直る」と読むか・何度まで引き直すかをここで決めている。
describe("hlsPlaylistMayBeStale", () => {
  let page;
  let win;
  beforeEach(() => {
    page = loadCommon({ html: "<!doctype html><html><body></body></html>" });
    win = page.win;
  });
  afterEach(async () => page.close());

  it("致命的なnetwork errorは引き直しの対象", () => {
    expect(win.hlsPlaylistMayBeStale({ fatal: true, type: "networkError" })).toBe(true);
  });

  it("hls.js自身が再試行する非致命は対象にしない", () => {
    expect(win.hlsPlaylistMayBeStale({ fatal: false, type: "networkError" })).toBe(false);
  });

  it("復号・decodeの失敗はlistを引き直しても直らない", () => {
    expect(win.hlsPlaylistMayBeStale({ fatal: true, type: "mediaError" })).toBe(false);
    expect(win.hlsPlaylistMayBeStale({ fatal: true, type: "otherError" })).toBe(false);
  });

  it("errorが無くても落ちない", () => {
    expect(win.hlsPlaylistMayBeStale(null)).toBe(false);
    expect(win.hlsPlaylistMayBeStale(undefined)).toBe(false);
  });
});

describe("hlsReloadGate", () => {
  let page;
  let win;
  beforeEach(() => {
    page = loadCommon({ html: "<!doctype html><html><body></body></html>" });
    win = page.win;
  });
  afterEach(async () => page.close());

  it("引き直しは1度きり(直らない失敗で読み直し続けない)", () => {
    const gate = win.hlsReloadGate();
    expect(gate.take()).toBe(true);
    expect(gate.take()).toBe(false);
    expect(gate.take()).toBe(false);
  });

  it("読み込みが進んだら(reset)また引き直せる", () => {
    const gate = win.hlsReloadGate();
    expect(gate.take()).toBe(true);
    gate.reset();
    expect(gate.take()).toBe(true);
  });

  it("playerごとに別の権利を持つ(片方の引き直しがもう片方を塞がない)", () => {
    const a = win.hlsReloadGate();
    const b = win.hlsReloadGate();
    expect(a.take()).toBe(true);
    expect(b.take()).toBe(true);
  });
});
