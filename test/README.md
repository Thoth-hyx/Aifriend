# 评测与回归测试

固定基线包含 32 条用例：14 条工程用例、18 条对话用例。对话评测使用群聊的生产上下文构造函数；单聊摘要更新和 ASR/TTS 不在这套基线的覆盖范围内。

## 运行

在项目根目录、激活虚拟环境后执行，无需启动前后端：

```powershell
python test/run.py
python test/run.py --list
python test/run.py --case reconnect_delta --case retry_attempt_fencing
python test/run.py --case short_preference --case long_preference --strict
```

默认离线，使用独立临时数据库，并阻止外部模型调用。`--strict` 将上下文缺失计入退出码；长期偏好用例目前会暴露群聊近期窗口之外的信息缺失。

需要真实模型评测时，先配置后端 `.env`，再显式运行：

```powershell
python test/run.py --live --case short_preference
```

`--live` 会调用当前配置的 LLM 及可能触发的工具，可能产生费用，不调用 ASR/TTS。

## 结果与边界

| 检查 | 判断内容 |
| --- | --- |
| 工程测试 | 消息去重、权限、同步、重试和旧任务保护等行为 |
| 离线上下文 | 必须出现的事实是否保留，禁止访问的信息是否混入输入 |
| 真实模型 | 答案关键词规则、耗时、首字时间、可获取的 token 用量 |

报告写入 `test/results/<运行编号>/report.json` 和 `cases.csv`，包含输入及来源信息。离线通过不代表模型答对；答案关键词命中仍需人工复核。

## 文件分类

- `datasets/baseline.json`：固定评测场景和规则。
- `run.py`：临时数据库、用例执行、真实模型适配与报告入口。
- `evaluation.py`：上下文/答案规则及结果汇总。
- `test_*.py`、`test_*.mjs`：评测工具、回复分段和音色上传等回归测试；群聊工程测试位于 `backend/web/test_group_im.py`。
