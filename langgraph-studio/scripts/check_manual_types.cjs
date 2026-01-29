#!/usr/bin/env node
/**
 * 手動型定義検出スクリプト
 *
 * api-generated.tsに対応するスキーマがあるのに手動定義している型を検出する
 */

const fs = require('fs');
const path = require('path');

const TYPES_DIR = path.join(__dirname, '..', 'src', 'types');
const API_GENERATED_PATH = path.join(TYPES_DIR, 'api-generated.ts');

// フロントエンド固有の型（バックエンドに対応がないため許可）
const ALLOWED_MANUAL_TYPES = new Set([
  // WebSocket関連（バックエンドはPythonでスキーマ定義なし）
  'WebSocketEventMap', 'WebSocketEventName', 'StateSyncData',
  'AgentEventData', 'AgentProgressData', 'AgentFailedData',
  'AgentActivatedData', 'AgentBudgetExceededData', 'AgentRetryData',
  'AgentPausedData', 'AgentResumedData', 'AgentWaitingProviderData',
  'AgentWaitingResponseData', 'AgentSpeechData', 'AgentLogData',
  'CheckpointCreatedData', 'CheckpointResolvedData',
  'AssetCreatedData', 'AssetUpdatedData',
  'InterventionCreatedData', 'InterventionAcknowledgedData',
  'InterventionProcessedData', 'InterventionDeletedData',
  'InterventionRespondedData', 'InterventionResponseAddedData',
  'NavigateData', 'ProjectInitializedData', 'ProjectPausedData',
  'ProjectStatusChangedData', 'ErrorStateData',

  // UI専用の型
  'MessagePriority', 'PhaseNumber', 'GameConcept',

  // Union型/Enum型（OpenAPIで表現しにくい）
  'AgentStatus', 'AgentType', 'LogLevel', 'OutputType',
  'ProjectStatus', 'CheckpointStatus', 'CheckpointType',
  'CheckpointResolution', 'InterventionPriority', 'InterventionTarget',
  'InterventionStatus', 'FileCategory', 'UploadedFileStatus',

  // フロントエンド専用の派生型
  'Agent', 'Project', 'Checkpoint', 'Intervention', 'UploadedFile',
  'ProjectMetrics', 'ProjectConfig', 'CreateProjectInput',
  'CheckpointOutput', 'CheckpointWithMeta', 'InterventionResponse',
  'CreateInterventionInput', 'InterventionWithMeta',
  'FileUploadInput', 'FileUploadResult', 'AgentMetrics',
  'LogEntry', 'AgentLogEntry', 'AgentOutput', 'QualityCheckConfig',
  'SequenceParticipant', 'SequenceMessage', 'SequenceData',
  'QualityCheckResult', 'BrushupOption', 'BrushupAgentOptions',
  'BrushupOptionsConfig', 'BrushupSuggestImage', 'BrushupConfig',
  'CostSettings', 'ServiceCostLimit', 'PricingUnit', 'ModelPricing',
  'ModelPricingInfo', 'PricingConfig',
]);

// api-generated.tsからスキーマ名を抽出
function extractGeneratedSchemas() {
  const content = fs.readFileSync(API_GENERATED_PATH, 'utf-8');
  const schemaMatch = content.match(/schemas:\s*\{([^}]+(?:\{[^}]*\}[^}]*)*)\}/s);
  if (!schemaMatch) return new Set();

  const schemas = new Set();
  const schemaRegex = /(\w+Schema|\w+Response):/g;
  let match;
  while ((match = schemaRegex.exec(content)) !== null) {
    schemas.add(match[1]);
  }
  return schemas;
}

// 型定義ファイルから手動定義を抽出
function extractManualTypes(filePath) {
  const content = fs.readFileSync(filePath, 'utf-8');
  const lines = content.split('\n');
  const types = [];

  // interface定義
  const interfaceRegex = /^export\s+interface\s+(\w+)/gm;
  let match;
  while ((match = interfaceRegex.exec(content)) !== null) {
    types.push({ name: match[1], line: content.substring(0, match.index).split('\n').length });
  }

  // type定義（api-generated.tsからの再エクスポートは除外）
  const typeRegex = /^export\s+type\s+(\w+)\s*=/gm;
  while ((match = typeRegex.exec(content)) !== null) {
    const lineNum = content.substring(0, match.index).split('\n').length;
    const lineContent = lines[lineNum - 1] || '';
    // components['schemas'] を含む行は再エクスポートなのでスキップ
    if (lineContent.includes("components['schemas']")) continue;
    types.push({ name: match[1], line: lineNum });
  }

  return types;
}

function main() {
  const generatedSchemas = extractGeneratedSchemas();
  const issues = [];

  // types/ディレクトリの全ファイルをスキャン
  const files = fs.readdirSync(TYPES_DIR).filter(f =>
    f.endsWith('.ts') &&
    f !== 'api-generated.ts' &&
    f !== 'index.ts'
  );

  for (const file of files) {
    const filePath = path.join(TYPES_DIR, file);
    const manualTypes = extractManualTypes(filePath);

    for (const { name, line } of manualTypes) {
      // 許可リストにあればスキップ
      if (ALLOWED_MANUAL_TYPES.has(name)) continue;

      // api-generated.tsに対応するスキーマがあれば警告
      const schemaName = name.endsWith('Schema') ? name : `${name}Schema`;
      const responseName = name.endsWith('Response') ? name : `${name}Response`;

      if (generatedSchemas.has(schemaName) || generatedSchemas.has(responseName)) {
        issues.push({
          file,
          line,
          name,
          suggestion: generatedSchemas.has(schemaName) ? schemaName : responseName
        });
      }
    }
  }

  console.log('============================================================');
  console.log('Manual Type Definition Check');
  console.log('============================================================');
  console.log();

  if (issues.length === 0) {
    console.log('No unauthorized manual type definitions found.');
    console.log();
    process.exit(0);
  }

  console.log(`[WARNING] Found ${issues.length} manual type(s) that should use api-generated.ts:`);
  console.log('------------------------------------------------------------');
  for (const issue of issues) {
    console.log(`  ${issue.file}:${issue.line} - ${issue.name}`);
    console.log(`    -> Use: import { components } from './api-generated'`);
    console.log(`    -> Type: components['schemas']['${issue.suggestion}']`);
  }
  console.log();
  console.log('To fix: Replace manual definitions with imports from api-generated.ts');
  console.log('Or add to ALLOWED_MANUAL_TYPES if this is intentionally frontend-only.');
  console.log();

  process.exit(1);
}

main();
