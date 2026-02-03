const fs = require("fs");
const os = require("os");
const path = require("path");

function deleteNulFiles(dir) {
  const deleted = [];
  try {
    const entries = fs.readdirSync(dir, { withFileTypes: true });
    for (const entry of entries) {
      const fullPath = path.join(dir, entry.name);
      if (entry.isDirectory()) {
        if (entry.name === "node_modules" || entry.name === ".git") continue;
        deleted.push(...deleteNulFiles(fullPath));
      } else if (entry.name === "nul") {
        fs.unlinkSync(fullPath);
        deleted.push(fullPath);
      }
    }
  } catch (_) {}
  return deleted;
}

let input = "";
process.stdin.on("data", (chunk) => (input += chunk));
process.stdin.on("end", () => {
  const projectRoot = path.resolve(__dirname, "..");
  const deletedFiles = deleteNulFiles(projectRoot);

  const messages = [];
  if (deletedFiles.length > 0) {
    messages.push(
      `[nul cleanup] ${deletedFiles.length} nul file(s) deleted: ${deletedFiles.join(", ")}`
    );
  }

  try {
    const data = JSON.parse(input);
    const sessionId = data.session_id;
    const filePath = path.join(os.tmpdir(), `claude-prompt-${sessionId}.txt`);
    if (fs.existsSync(filePath)) {
      const prompt = fs.readFileSync(filePath, "utf8");
      if (prompt) {
        messages.push("--- Original Prompt ---\n" + prompt);
      }
    }
  } catch (_) {}

  if (messages.length > 0) {
    console.log(JSON.stringify({ systemMessage: messages.join("\n") }));
  }
  process.exit(0);
});
