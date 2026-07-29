import { describe, it, expect, afterEach } from "vitest";
import { loadPage } from "./helpers/page.js";

// 11枚の HTML はすべて common.js を classic script で読み、その後に page 固有の JS を読む。
// この構成が壊れる(関数名の衝突・page JS が common.js より先に必要な物を触る・
// bootstrap が DOM に無い id を掴む)と画面は白いまま何も出さない。
// 各 page を実際に組み立てて、読み込みと bootstrap が例外なく通ることを確かめる。
const PAGES = [
  ["index", "/"],
  ["overview", "/overview"],
  ["history", "/history"],
  ["streamers", "/streamers"],
  ["videos", "/videos"],
  ["capacity", "/capacity"],
  ["fans", "/fans"],
  ["analytics", "/analytics"],
  ["jobs", "/jobs"],
  ["ops", "/ops"],
  ["settings", "/settings"],
];

describe("各画面の読み込み", () => {
  let page;
  afterEach(async () => {
    if (page) await page.close();
    page = null;
  });

  it.each(PAGES)("%s.html が JS error 無しで組み上がる", async (name, path) => {
    page = loadPage({ page: name, url: `http://localhost:8520${path}` });
    page.fireReady();
    await page.settle();

    expect(page.errors.map(String)).toEqual([]);
    // common.js が最初に読まれていること(page JS は common.js の関数へ依存している)。
    expect(page.loaded[0]).toBe("common.js");
  });

  it.each(PAGES)("%s.html の nav が全 page 分描画され、現在地に active が付く", (name, path) => {
    page = loadPage({ page: name, url: `http://localhost:8520${path}` });
    const links = Array.from(page.document.querySelectorAll("nav.a-nav a"));
    expect(links.length).toBe(11);
    const active = links.filter((a) => a.className === "active");
    expect(active.map((a) => a.getAttribute("href"))).toEqual([path]);
  });
});
