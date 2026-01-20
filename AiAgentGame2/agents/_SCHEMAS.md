# Agent共通スキーマ

## 共通型定義

```typescript
interface WorkerTask {
  worker: string;
  task: string;
  status: "completed" | "failed" | "retried";
  attempts: number;
}

interface QualityCheck {
  [key: string]: boolean;
}

interface ReviewItem {
  type: string;
  description: string;
  recommendation: string;
}

interface LeaderOutputBase {
  worker_tasks: WorkerTask[];
  quality_checks: QualityCheck;
  human_review_required: ReviewItem[];
}
```

## Phase1: 企画

### ConceptInput/Output
```typescript
interface ConceptInput {
  user_idea: string;
  constraints?: {platform?: string; scope?: "mvp"|"full"; deadline?: string};
  previous_feedback?: string;
}

interface ConceptOutput {
  title: string;
  tagline: string;
  elevator_pitch: string;
  genre: {primary: string; secondary?: string[]};
  target_audience: {age_range: string; gamer_type: string; play_style: string; session_length: string};
  platform: {primary: string; technical_base: string};
  core_loop: {description: string; steps: string[]; hook: string};
  key_mechanics: Array<{name: string; description: string; player_action: string; feedback: string}>;
  progression_system: {type: string; elements: string[]; pacing: string};
  unique_selling_points: Array<{point: string; why_unique: string; player_benefit: string}>;
  comparable_games: Array<{title: string; similarity: string; difference: string}>;
  scope: {mvp_features: string[]; phase2_features: string[]; out_of_scope: string[]};
  risks: Array<{risk: string; impact: "high"|"medium"|"low"; mitigation: string}>;
  approval_questions: string[];
}
```

### DesignInput/Output
```typescript
interface DesignInput {
  concept: ConceptOutput;
  previous_feedback?: string;
}

interface DesignOutput {
  technical_architecture: {engine: string; language: string; frameworks: string[]};
  game_systems: Array<{name: string; description: string; components: string[]}>;
  data_structures: Array<{name: string; fields: Record<string, string>}>;
  ui_layout: {screens: Array<{name: string; elements: string[]}>};
  asset_requirements: Array<{type: string; items: string[]}>;
}
```

### ScenarioOutput
```typescript
interface ScenarioOutput {
  world_setting: {name: string; description: string; rules: string[]};
  story_outline: {premise: string; acts: Array<{name: string; events: string[]}>};
  characters: Array<{name: string; role: string; personality: string}>;
  dialogues: Array<{scene: string; lines: Array<{speaker: string; text: string}>}>;
}
```

### CharacterOutput
```typescript
interface CharacterOutput {
  characters: Array<{
    id: string;
    name: string;
    role: "player"|"npc"|"enemy"|"boss";
    visual: {style: string; colors: string[]; features: string[]};
    stats: Record<string, number>;
    abilities: Array<{name: string; effect: string}>;
    ai_behavior?: {type: string; patterns: string[]};
  }>;
}
```

### WorldOutput
```typescript
interface WorldOutput {
  maps: Array<{
    id: string;
    name: string;
    type: string;
    size: {width: number; height: number};
    terrain: Array<{type: string; coverage: number}>;
    objects: Array<{type: string; positions: string[]}>;
    connections: string[];
  }>;
  environment: {lighting: string; weather: string[]; time_system: boolean};
}
```

## Phase2: 開発

### CodeTaskInput/Output
```typescript
interface CodeTaskInput {
  task_id: string;
  description: string;
  design_ref: string;
  dependencies: string[];
  priority: "critical"|"high"|"medium"|"low";
}

interface CodeOutput {
  task_id: string;
  files: Array<{path: string; content: string; type: "new"|"modified"}>;
  tests: Array<{name: string; status: "pass"|"fail"}>;
  issues: Array<{type: string; description: string; severity: string}>;
}
```

### AssetTaskOutput
```typescript
interface AssetOutput {
  task_id: string;
  assets: Array<{
    id: string;
    type: "sprite"|"audio"|"ui"|"tilemap";
    path: string;
    metadata: Record<string, any>;
  }>;
}
```

## Phase3: 品質

### IntegratorOutput
```typescript
interface IntegratorOutput extends LeaderOutputBase {
  build: {version: string; status: "success"|"failed"; artifacts: string[]};
  integration_tests: Array<{name: string; status: "pass"|"fail"}>;
  merge_conflicts: Array<{file: string; resolved: boolean}>;
}
```

### TesterOutput
```typescript
interface TesterOutput extends LeaderOutputBase {
  test_report: {
    summary: {total: number; passed: number; failed: number; skipped: number};
    coverage: number;
    performance: {fps: number; memory_mb: number; load_time_ms: number};
  };
  bug_reports: Array<{id: string; severity: "critical"|"major"|"minor"; description: string; steps: string[]}>;
  quality_gates: Array<{name: string; threshold: number; actual: number; passed: boolean}>;
}
```

### ReviewerOutput
```typescript
interface ReviewerOutput extends LeaderOutputBase {
  code_review: Array<{file: string; issues: Array<{line: number; type: string; message: string}>}>;
  design_review: {compliance: number; deviations: string[]};
  security_review: {vulnerabilities: Array<{type: string; severity: string; location: string}>};
  final_verdict: "approved"|"needs_revision"|"rejected";
}
```
