# tiny_assign：小型任务分配

某班组有 4 名工人（W1–W4）和 4 项任务（J1–J4）。需要把任务分配给工人，使总成本最小。

## 业务规则

1. 每名工人至多承担 1 项任务。
2. 每项任务必须恰好由 1 名工人完成。
3. 工人 W2 不具备任务 J3 所需资质，**W2 不能接任务 J3**。

## 数据

`data/costs.csv`：三列 `worker,job,cost`，表示工人 worker 完成任务 job 的成本。

## 输出要求

把求解结果写入本程序所在目录的 `solution.json`，格式：

```json
{
  "objective": <总成本>,
  "assignments": [{"worker": "W1", "job": "J2", "cost": 11}, ...]
}
```

同时在标准输出打印一行 `OBJECTIVE <总成本>`。
