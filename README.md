# 12345 涉检线索智能筛查工具 MVP

面向政法机关的 12345 市民热线涉检线索智能筛查原型系统。系统支持多批次工单手动导入、公益成案领域筛查、弱势群体筛查、行政违法筛查、拖欠工资专项导出、屡诉未决聚合、风险预警、人工确认、RBAC 权限和审计留痕。

## 技术栈

- 前端：React + TypeScript + Vite
- 后端：FastAPI + SQLAlchemy + SQLite
- 数据处理：openpyxl
- 智能筛查：本地规则引擎，预留大模型适配器

## 快速启动

### 单链接启动，推荐落地试用

```bash
cd /Users/wang/Desktop/青创北京/qingchuang-12345-clue-screening
bash scripts/start_web.sh
```

启动后，同一内网中的用户访问：

```text
http://服务器IP:8000
```

即可打开系统并完成登录、上传、筛查、检索、确认、导出等全部操作。若只在本机试用，访问 `http://127.0.0.1:8000`。

### 开发模式

```bash
cd /Users/wang/Desktop/青创北京/qingchuang-12345-clue-screening
bash scripts/init_backend.sh
bash scripts/start_backend.sh
```

另开终端：

```bash
cd /Users/wang/Desktop/青创北京/qingchuang-12345-clue-screening
bash scripts/start_frontend.sh
```

访问 `http://localhost:5173`。

## 演示账号

| 账号 | 密码 | 权限 |
|---|---|---|
| `admin` | `admin123` | 全部权限 |
| `prosecutor` | `prosecutor123` | 查看、筛查、复核、导出 |
| `reviewer` | `reviewer123` | 查看、复核 |
| `viewer` | `viewer123` | 只读 |

这些账号仅用于本地演示，上线前必须更换。

## 核心功能

- 数据导入是第一个业务板块，系统初始化后不自动导入数据，支持多个 Excel 批次并存。
- 用户手动上传 Excel 后不会替换旧批次；可勾选批次运行公益成案领域、弱势群体、行政违法筛查，也可删除选中批次。
- 系统按 Excel 表头映射标准字段，缺列自动为空，多出的列会保存在详情和导出中；展示、导出、模型调用均保留原始数据，不做脱敏。
- 公益成案领域、弱势群体、行政违法均按线索标注规则生成分类结果，未命中规则的数据进入“未知领域”或“其他”。
- “线索标注”独立维护，支持按板块新增、编辑、删除和启停，规则变更后重新运行筛查即可更新待确认分类结果。
- “预警研判”统一承载屡诉未决、预警中心、履职异常与趋势分析，围绕“长期存在、多次反映、仍未解决”输出介入建议。
- 工单库支持按标题、正文、问题分类、工单编号等字段进行关键词检索或语义检索；拖欠工资类数据可导出“核心内容提炼”。
- 根据未解决、不满意、公共安全、投诉频次生成风险等级。
- 各业务页面右上角提供选择导出和去除已导出筛选，导出成功后工单全局标记为已导出。
- 登录、查看详情、导入、筛查、复核、导出均写入审计日志。

## 大模型配置

默认不启用外部模型。后端提供 `LLMAdapter`，按 OpenAI-compatible 方式预留：

```env
LLM_ENABLED=true
LLM_BASE_URL=https://example.com/v1
LLM_API_KEY=your-key
LLM_MODEL=your-model
```

当前版本按业务要求使用原始工单内容进行模型增强。政法机关部署建议优先使用私有化或专有云模型，并在启用外部模型前完成数据出域审批。

## 目录

```text
backend/   FastAPI 后端
frontend/  React 管理后台
data/      样例数据、导出文件
docs/      安全设计和运行手册
scripts/   初始化和启动脚本
```
