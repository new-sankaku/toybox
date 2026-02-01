const fs = require('fs');
const path = require('path');
const glob = require('glob');

const CHECK_TYPE = process.argv[2];

function checkSurfaceClassUsage() {
  const srcDir = path.join(__dirname, '..', 'src');
  const files = glob.sync('**/*.tsx', { cwd: srcDir });
  const violations = [];
  const bgPattern = /bg-nier-bg-(header|main|footer)/g;
  const surfaceClasses = ['nier-surface-main', 'nier-surface-panel', 'nier-surface-header', 'nier-surface-footer', 'nier-surface-selected'];

  for (const file of files) {
    const filePath = path.join(srcDir, file);
    const content = fs.readFileSync(filePath, 'utf-8');
    const lines = content.split('\n');

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      const classNameMatch = line.match(/className\s*=\s*["'`{][^"'`}]*/g);
      if (!classNameMatch) continue;

      for (const match of classNameMatch) {
        const hasDarkBg = /bg-nier-bg-(header|footer)/.test(match);
        const hasTextClass = /text-nier-text-/.test(match);
        const hasSurfaceClass = surfaceClasses.some(sc => match.includes(sc));

        if (hasDarkBg && hasTextClass && !hasSurfaceClass) {
          violations.push({
            file,
            line: i + 1,
            issue: 'bg-nier-bg-* と text-nier-text-* の直接組み合わせ',
            snippet: line.trim().substring(0, 80)
          });
        }
      }
    }
  }

  if (violations.length > 0) {
    for (const v of violations) {
      console.log(`  ${v.file}:${v.line}: ${v.issue}`);
      console.log(`    ${v.snippet}`);
    }
    return false;
  }
  return true;
}

function checkColorEmoji() {
  const srcDir = path.join(__dirname, '..', 'src');
  const files = glob.sync('**/*.tsx', { cwd: srcDir });
  const violations = [];
  const emojiPattern = /[📋🔍⚡📁📂🎮🎯🚀💡🔧🔨📊📈📉🔔🔕💾📤📥🗑️✏️🔒🔓👤👥⭐🌟💫✨🎉🎊🔴🟢🟡🟠⚠️❌✅❗❓🔵⚪]/g;

  for (const file of files) {
    const filePath = path.join(srcDir, file);
    const content = fs.readFileSync(filePath, 'utf-8');
    const lines = content.split('\n');

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (line.trimStart().startsWith('//')) continue;
      const matches = line.match(emojiPattern);
      if (matches) {
        violations.push({
          file,
          line: i + 1,
          emojis: [...new Set(matches)].join(' '),
          snippet: line.trim().substring(0, 60)
        });
      }
    }
  }

  if (violations.length > 0) {
    for (const v of violations) {
      console.log(`  ${v.file}:${v.line}: カラー絵文字 [${v.emojis}]`);
    }
    return false;
  }
  return true;
}

function checkInlineStyles() {
  const srcDir = path.join(__dirname, '..', 'src');
  const files = glob.sync('**/*.tsx', { cwd: srcDir });
  const violations = [];
  const allowedPatterns = [
    /['"]?--/,
    /['"]?(width|height|minWidth|maxWidth|minHeight|maxHeight|top|left|right|bottom)/,
    /['"]?(transform|position|opacity|fontSize|zIndex|flex|lineHeight)/,
    /['"]?(margin|padding|background|color)/,
    /['"]?(gridTemplate|gap|overflow|visibility|display)/,
    /\{[a-zA-Z]+\}/,
  ];

  for (const file of files) {
    const filePath = path.join(srcDir, file);
    const content = fs.readFileSync(filePath, 'utf-8');
    const lines = content.split('\n');

    for (let i = 0; i < lines.length; i++) {
      const line = lines[i];
      if (/style\s*=\s*\{\s*\{/.test(line)) {
        const styleContent = line.match(/style\s*=\s*\{\s*\{([^}]*)/);
        if (styleContent) {
          const isAllowed = allowedPatterns.some(p => p.test(styleContent[1]));
          if (isAllowed) continue;
        }
        if (/style\s*=\s*\{\s*\{$/.test(line.trim())) continue;
        violations.push({
          file,
          line: i + 1,
          snippet: line.trim().substring(0, 70)
        });
      }
    }
  }

  if (violations.length > 0) {
    for (const v of violations) {
      console.log(`  ${v.file}:${v.line}: インラインスタイル検出`);
      console.log(`    ${v.snippet}`);
    }
    return false;
  }
  return true;
}

function checkWebSocketHandlers() {
  const wsServicePath = path.join(__dirname, '..', 'src', 'services', 'websocketService.ts');
  const content = fs.readFileSync(wsServicePath, 'utf-8');

  const interfaceMatch = content.match(/interface ServerToClientEvents\s*\{([\s\S]*?)\n\}/);
  if (!interfaceMatch) {
    console.log('  ServerToClientEvents interface not found');
    return false;
  }

  const definedEvents = [];
  const eventPattern = /'([^']+)':/g;
  let match;
  while ((match = eventPattern.exec(interfaceMatch[1])) !== null) {
    definedEvents.push(match[1]);
  }

  const handlerPattern = /this\.socket\.on\s*\(\s*'([^']+)'/g;
  const handledEvents = [];
  while ((match = handlerPattern.exec(content)) !== null) {
    handledEvents.push(match[1]);
  }

  const builtinEvents = ['connect', 'disconnect', 'error'];
  const missingHandlers = definedEvents.filter(
    e => !handledEvents.includes(e) && !builtinEvents.includes(e)
  );
  const extraHandlers = handledEvents.filter(
    e => !definedEvents.includes(e) && !builtinEvents.includes(e)
  );

  if (missingHandlers.length > 0 || extraHandlers.length > 0) {
    if (missingHandlers.length > 0) {
      console.log('  Missing handlers for defined events:');
      missingHandlers.forEach(e => console.log(`    - ${e}`));
    }
    if (extraHandlers.length > 0) {
      console.log('  Handlers for undefined events:');
      extraHandlers.forEach(e => console.log(`    - ${e}`));
    }
    return false;
  }
  return true;
}

let result = true;

switch (CHECK_TYPE) {
  case 'surface':
    result = checkSurfaceClassUsage();
    break;
  case 'emoji':
    result = checkColorEmoji();
    break;
  case 'inline-style':
    result = checkInlineStyles();
    break;
  case 'websocket':
    result = checkWebSocketHandlers();
    break;
  default:
    console.log('Usage: build_checks.cjs <surface|emoji|inline-style|websocket>');
    process.exit(1);
}

process.exit(result ? 0 : 1);
