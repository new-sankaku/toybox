import asyncio
from collections import defaultdict, deque
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set, Tuple
from middleware.logger import get_logger


class TaskDAG:
    def __init__(self, tasks: List[Dict[str, Any]]):
        self._tasks = {t["id"]: t for t in tasks}
        self._adj: Dict[str, Set[str]] = defaultdict(set)
        self._in_degree: Dict[str, int] = {t["id"]: 0 for t in tasks}
        for t in tasks:
            for dep in t.get("depends_on", []):
                if dep in self._tasks:
                    self._adj[dep].add(t["id"])
                    self._in_degree[t["id"]] += 1

    def get_execution_layers(self) -> List[List[str]]:
        in_deg = dict(self._in_degree)
        queue = deque(tid for tid, d in in_deg.items() if d == 0)
        layers: List[List[str]] = []
        while queue:
            layer = list(queue)
            layers.append(layer)
            queue = deque()
            for tid in layer:
                for child in self._adj[tid]:
                    in_deg[child] -= 1
                    if in_deg[child] == 0:
                        queue.append(child)
        scheduled = {tid for layer in layers for tid in layer}
        missing = set(self._tasks.keys()) - scheduled
        if missing:
            get_logger().warning(f"DAG循環検出、残タスクを最終レイヤーに追加: {missing}")
            layers.append(list(missing))
        return layers

    def get_task(self, task_id: str) -> Optional[Dict[str, Any]]:
        return self._tasks.get(task_id)

    @property
    def task_count(self) -> int:
        return len(self._tasks)


def normalize_worker_tasks(raw_tasks: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    normalized = []
    for i, t in enumerate(raw_tasks):
        task_id = t.get("id", f"task_{i}")
        normalized.append(
            {
                "id": task_id,
                "worker": t.get("worker", ""),
                "task": t.get("task", ""),
                "depends_on": t.get("depends_on", []),
            }
        )
    return normalized


async def execute_dag_parallel(
    dag: TaskDAG,
    execute_fn: Callable[[Dict[str, Any]], Coroutine[Any, Any, Any]],
    on_layer_start: Optional[Callable[[int, List[str]], None]] = None,
) -> List[Tuple[str, Any]]:
    layers = dag.get_execution_layers()
    all_results: List[Tuple[str, Any]] = []
    logger = get_logger()
    for layer_idx, layer in enumerate(layers):
        if on_layer_start:
            on_layer_start(layer_idx, layer)
        logger.info(f"DAG Layer {layer_idx}: {len(layer)}タスク並列実行 {layer}")
        tasks_to_run = []
        for tid in layer:
            task_data = dag.get_task(tid)
            if task_data:
                tasks_to_run.append((tid, execute_fn(task_data)))
        if len(tasks_to_run) == 1:
            tid, coro = tasks_to_run[0]
            result = await coro
            all_results.append((tid, result))
        elif tasks_to_run:
            coros = [coro for _, coro in tasks_to_run]
            results = await asyncio.gather(*coros, return_exceptions=True)
            for (tid, _), result in zip(tasks_to_run, results):
                if isinstance(result, Exception):
                    logger.error(f"DAGタスク例外: {tid}: {result}", exc_info=True)
                all_results.append((tid, result))
    return all_results
