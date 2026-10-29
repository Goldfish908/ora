# R0 适配检查（fit-gap）——5195 任务书 §7 R0

日期：2026-10-29。全部为本机实测/实查，未做任何假设性声明。

## 1. 硬件

| 资源 | 实测 |
|---|---|
| s142（本机） | 48 核 CPU / 503GB RAM / **无 GPU**(nvidia-smi 无驱动） |
| 训练用 GPU | 任务书提到的两张 A800 不在本机，**位置待用户确认** |
| 结论 | 本机可承担：数据生成调度、witness/编译 CPU 执行、API 推理编排、工程路径全部工作；LoRA 训练与本地模型推理必须依赖外部 GPU |

## 2. 模型可得性

| 模型 | 状态 |
|---|---|
| Qwen/Qwen3.5-9B | HF 存在，Apache-2.0,tag `qwen3_5`，混合结构（Gated DeltaNet + 门控注意力，原生多模态）——与 prereg §6.1 预期一致 |
| Chenyu-Zhou/StepORLM-Qwen3-8B | HF 存在（P3 成对比较①） |
| JamesX421/SOLID-StepORLM-Qwen3-8B | HF 存在（成对比较②) |
| Aurora-Gem/PEARL-Qwen3-4B-Instruct-2507 | HF 存在（成对比较③，注意基座是 Qwen3-4B-Instruct-2507） |
| MaaS（实验室端点，183 模型） | **无 Qwen3.5-9B、无 Qwen3-8B**；有 qwen3.5-27b / qwen3.5-flash / qwen3.8-27b（现 actor） |

**关键结论（回答 prereg §11.4)**：motivation 研究 M1/M2 的主模型 Qwen3.5-9B(thinking 开/关）**无法走现有 MaaS**，必须本地 GPU(vLLM）或另找 API 渠道；9 个本地模型配置的 6–8 GPU 时估算成立的前提是先有卡。27B 规模验证可走 MaaS(qwen3.5-27b）或本地。

## 3. 训练栈

| 组件 | 状态 |
|---|---|
| Axolotl | PyPI 最新 0.21.1;**官方已支持 Qwen3.5**（有 9b-lora 示例配置）：混合结构 LoRA 需显式加 `linear_attn.in_proj_qkv/in_proj_z/out_proj` 目标模块；sample_packing 需装 `flash-linear-attention==0.5.2`（否则 RuntimeError);建议配 Cut Cross Entropy 降显存。9B LoRA 单卡可跑（9b-lora-vision 为单卡配置） |
| PEFT/TRL | PyPI 正常，未实测版本兼容（窗口前冒烟覆盖） |
| vLLM | 未实测；Qwen3.5 线性注意力推理需对应内核，**窗口前必须冒烟**（prereg §7.4 已列） |

## 4. 求解器

- SCIP/pyscipopt：本机就绪（4.3.0,rl env)，受控集与 witness 执行已在用。
- Gurobi/COPT 学术许可：**未确认**（motivation §8.3 的"需你确认"项）。RetailOpt-190 规模超免费上限，若许可拿不到，退路是 Pyomo+HiGHS（有已知代价）。
- HiGHS:pip 可装，CPU 即可，作为备选已验证可用性（本机 pyscipopt 生态内）。

## 5. 网络

外网经代理 `http://127.0.0.1:7893`(HF/PyPI 实测可达）;LLM 端点必须 `--noproxy` 直连。HF 模型下载（9B BF16 ~18GB）经代理可行但速度未测。

## 6. 阻塞项清单（需用户确认）

1. **两张 A800 的位置与到达方式**(R 全部训练 + 9B 本地推理的前提）;
2. Gurobi/COPT 学术许可（RetailOpt-190 的 M1 前提，或接受 HiGHS 退路）;
3. 72h GPU 窗口日期与可否拆分（prereg §11.1);
4. thinking 训练与否的复议时点 = motivation P4 结果之后（v0.2 §7，无需现在决定）。
