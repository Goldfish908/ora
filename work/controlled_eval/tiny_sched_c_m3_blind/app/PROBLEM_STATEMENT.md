# tiny_sched：小型双机调度

5 个作业（J1–J5）要在 2 台机器（M1、M2）上加工，目标是最小化完工时间（makespan，即最晚作业的完成时刻）。

## 业务规则

1. 每个作业必须完整地分配到恰好一台机器上，加工不可中断。
2. 同一台机器上任意两个作业的加工区间不得重叠。
3. 时序约束见 `data/precedence.csv`：J1 必须先于 J3，即 **J1 的完成时刻 ≤ J3 的开始时刻**。
4. 每个作业在机器上的占用时长为其加工时间 `proc_min`（分钟）。`jobs.csv` 中的 `setup_min` 是换模准备时间，由工装组离线完成，**不占用机台**，不进入排程。

## 数据

- `data/jobs.csv`：`job_id,proc_min,setup_min`。
- `data/machines.csv`：`machine_id`，可用机器列表，两台机器速度相同，时刻 0 均可用。
- `data/precedence.csv`：`pred,succ`，先后关系。

## 输出要求

把求解结果写入本程序所在目录的 `solution.json`，格式：

```json
{
  "makespan": 17,
  "jobs": [{"job_id": "J1", "machine": "M2", "start": 0, "proc": 3, "end": 3}, ...]
}
```

其中 `proc` 为该作业实际采用的加工时长，`end = start + proc`。同时在标准输出打印一行 `OBJECTIVE <makespan>`。
