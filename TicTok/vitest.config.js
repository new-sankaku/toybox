import { defineConfig } from "vitest/config";

// static/ の JS は ES module ではなく classic script (HTML の <script src>) で読まれる。
// test 側もその読み方をそのまま再現する (tests/js/helpers/page.js が jsdom へ流し込む) ため、
// vitest 自身の environment は node のままでよい。jsdom は helper が明示的に組み立てる。
export default defineConfig({
  test: {
    root: ".",
    include: ["tests/js/**/*.test.js"],
    environment: "node",
    globals: false,
    // 日時 helper は toLocaleString("ja-JP") で書式を作る。実行機の timezone に結果が
    // 引きずられないよう、app の既定 (config.get_locale_tz) と同じ帯へ固定する。
    env: { TZ: "Asia/Tokyo" },
    reporters: ["default"],
    coverage: {
      provider: "v8",
      include: ["static/*.js"],
      exclude: ["static/vendor/**"],
      reportsDirectory: "coverage/js",
    },
  },
});
