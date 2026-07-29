import { describe, it, expect, afterEach } from "vitest";
import { loadCommon } from "./helpers/page.js";

describe("common.js の読み込み", () => {
  let page;
  afterEach(() => page && page.close());

  it("classic script として評価でき、共通helperがglobalへ生える", () => {
    page = loadCommon();
    expect(page.errors).toEqual([]);
    expect(typeof page.win.fmtNum).toBe("function");
    expect(typeof page.win.renderTableRows).toBe("function");
    expect(typeof page.win.apiSend).toBe("function");
  });
});
