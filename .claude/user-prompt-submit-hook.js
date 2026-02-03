const fs = require("fs");
const os = require("os");
const path = require("path");

let input = "";
process.stdin.on("data", (chunk) => (input += chunk));
process.stdin.on("end", () => {
  try {
    const data = JSON.parse(input);
    const prompt = data.prompt;
    const sessionId = data.session_id;
    if (prompt && sessionId) {
      const filePath = path.join(os.tmpdir(), `claude-prompt-${sessionId}.txt`);
      fs.writeFileSync(filePath, prompt, "utf8");
    }
  } catch (_) {}
  process.exit(0);
});
