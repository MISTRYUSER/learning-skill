# Learning Skill

一个用于技术知识、论文、源码、系统设计、AI/Agent 与后端工程学习的 Codex Skill。

目标是让学习者在没有资料和提示的情况下，独立解决一个新的相关问题。默认中文、先问再讲，通过主动回忆、生成式学习、工程实践、具体反馈与迁移测试验证能力。

## 安装

在 Codex 中请求：

> 使用 skill-installer，从 https://github.com/MISTRYUSER/learning-skill 安装 learning 目录中的 Skill。

也可手动安装到用户级技能目录。下面以尚未安装 learning 为例；已有同名 Skill 时先备份：

```sh
git clone https://github.com/MISTRYUSER/learning-skill.git
mkdir -p "${CODEX_HOME:-$HOME/.codex}/skills"
cp -R learning-skill/learning "${CODEX_HOME:-$HOME/.codex}/skills/learning"
```

## 使用

在 Codex 对话中输入：

```text
$learning /learn Agent Memory
$learning /review
$learning /practice 缓存击穿
$learning /source /你的项目路径
$learning /paper 论文链接或文件路径
```

这些命令是 Skill 理解的对话语义，不要求宿主注册斜杠命令。也可直接说“学习 RAG”“测一下我”或“继续学习”。

| 命令 | 用途 |
|---|---|
| `/learn <topic>` | 预测试、知识地图和针对性训练 |
| `/review` | 检查到期复习及历史错误，先出题 |
| `/quiz <topic>` | 只测试与判分，不主动讲解答案 |
| `/explain <topic>` | 先尝试，再解释，解释后闭卷测试 |
| `/practice <topic>` | 编码、调试、设计等工程实践 |
| `/source <repo/path>` | 从问题、入口与调用链理解源码 |
| `/paper <paper>` | 研究问题、方法、实验、复现与迁移 |
| `/status` | 查看掌握等级、到期数量与待答任务 |
| `/weakness` | 查看优先薄弱点及下一种练习 |
| `/errors` | 查看真实错误与纠正、复习时间 |
| `/reset <topic>` | 重置指定主题，保留可恢复备份 |

## 学习与掌握判定

默认流程：预测试 → 知识地图 → 聚焦学习 → 闭卷回忆 → 实践 → 反馈 → 迁移测试。

每次只选 3～7 个核心知识点，逐题交互；根据错误来源调整训练，混合相关主题，不机械重复同题。看完资料、复述定义或说“懂了”不会被判定为掌握。

掌握等级为 0～5。只有 Level ≥ 4 算掌握，要求独立通过真实应用和新场景迁移题。Level 5 还要求处理复杂变体并解释取舍。助手给出的答案、提示后的成功和开卷回答不替代独立能力证据。

## 状态与复习

学习状态默认保存在 `$CODEX_HOME/learning/`，未设置 CODEX_HOME 时为 `~/.codex/learning/`，与安装在 `skills/learning/` 的 Skill 代码分开。已有用户指定路径时沿用。没有文件工具时只维护当前会话状态。

```text
learning/
  profile.md
  topics.json
  error_log.jsonl
  review_queue.json
  sessions/
  notes/
```

只记录学习偏好、掌握证据、简短错误摘要、复习日期和进度，不保存完整聊天或整份资料。

默认间隔为 1、3、7、14、30 天；答错缩短到最多 1 天。到期前即时练习不会跳过间隔或推迟已有日期。复习队列在调用 Skill 时检查，不自动发送提醒。

数据结构预留 FSRS 字段和评估事件。**当前内置脚本是固定间隔调度器，不是 FSRS 引擎。** 接入实际可用的 FSRS 引擎时按 [状态说明](learning/references/state.md#fsrs-适配) 迁移；FSRS 记忆保持预测与工程掌握等级分开。

## 文件结构

```text
learning/
  SKILL.md
  agents/openai.yaml
  references/
    modes.md
    state.md
    templates.md
  scripts/learning_state.py
  assets/
    profile.md
    point.json
    assessment.json
tests/test_learning_state.py
```

[SKILL.md](learning/SKILL.md) 是入口，其他文件按需读取。assets 中是模板和示例，不能作为真实学习证据提交。

状态脚本使用 Python 3.9+ 标准库，文件锁依赖 Unix `fcntl`。它能校验数据与掌握证据字段，但无法判定用户是否偷看、答案真实性或评估是否正确；这些由实际交互与验证负责。

## 验证

```sh
python3 -m unittest discover -s tests -p 'test_*.py' -v
```

测试覆盖间隔推进、即时重复、错误回退、重复提交、掌握门槛、提示回答、队列交错、FSRS 保护、状态恢复与主题重置。Skill 另经过结构校验和新主题/自报掌握两个独立场景的前向模拟。
