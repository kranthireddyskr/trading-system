from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from typing import Callable


@dataclass
class OptimizationResult:
    params: dict[str, float]
    score: float

    def __repr__(self) -> str:
        return f"OptimizationResult(params={self.params!r}, score={self.score:.2f})"


class StrategyOptimizer:
    def __repr__(self) -> str:
        return "StrategyOptimizer()"

    def optimize(self, param_grid: dict[str, list[float]], evaluator: Callable[[dict[str, float]], float]) -> OptimizationResult:
        keys = list(param_grid.keys())
        best = OptimizationResult({}, float("-inf"))
        for values in product(*[param_grid[key] for key in keys]):
            params = dict(zip(keys, values))
            score = float(evaluator(params))
            if score > best.score:
                best = OptimizationResult(params=params, score=score)
        return best

