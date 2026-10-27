# 文档索引

| 文件 | 内容 |
|---|---|
| [design.md](design.md) | 选型与架构（v0.3）：流水线、竖排规格、8 GB 档位、里程碑 |
| [portable-data-contract.md](portable-data-contract.md) | `data/` 目录、`config.json`、`models/manifest.json`、`secrets.enc` 契约 |
| [release-checklist.md](release-checklist.md) | 发布前逐条检查（合规 / 便携 / 质量 / 材料） |
| [user-guide.txt](user-guide.txt) | 最终用户说明（随便携包发布） |
| [notes/ballonstranslator-review.md](notes/ballonstranslator-review.md) | 对 BallonsTranslator 的架构评审：借鉴与规避 |

## 读的顺序

1. 新贡献者：`README.md` → `AGENTS.md` → `design.md` §4（架构）
2. 改排版：`design.md` §5.6、§7（竖排规格）→ 跑 `tests/golden/`
3. 改打包/配置：`portable-data-contract.md` → `release-checklist.md`